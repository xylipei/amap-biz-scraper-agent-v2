"""
智能体编排模块 - DeepSeek意图解析与任务编排

职责：
- 调用DeepSeek API解析用户自然语言输入，提取区域、品类、修饰词
- 处理复合输入场景（场景A/B）
- 编排任务流程：fetch_pois -> aggregate_and_clean -> parse_groupbuy_info -> export_to_table
- 统计结果汇报

防跑偏要求（PRD 3.2）：
- 场景B：自动将"水果团购"修正为"水果店"/"水果超市"，强制过滤无团购商家
- 缺失核心参数时追问用户
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI, APIError

from amap_agent.config import (
    AMAP_API_KEY,
    DEEPSEEK_API_KEY,
    validate_config,
)
from amap_agent.fetcher import fetch_pois
from amap_agent.groupbuy import parse_groupbuy_info
from amap_agent.aggregator import aggregate_and_clean, apply_groupbuy_filter
from amap_agent.exporter import export_to_table, save_search_history

logger = logging.getLogger(__name__)

# DeepSeek 配置
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 意图解析的System Prompt
INTENT_SYSTEM_PROMPT = """你是一个高德地图搜索Agent的意图解析器。你的任务是将用户的自然语言输入解析为结构化的搜索参数。

请分析用户输入，输出JSON格式的结果（不要包含markdown代码块标记），包含以下字段：
- "region": 具体区域，**必须只包含区县级或街道级名称**（如"海淀区"、"西湖区"、"闵行区"）。如果用户输入了城市+区县（如"杭州西湖区"），只提取"西湖区"，不要保留城市名。如果无法拆分到区县级，则留空字符串。
- "city": 城市级名称（如"北京"、"杭州"、"上海"、"深圳"）。如果用户只指定了区县名但没有城市，可以从区县推断所属城市（例如"西湖区"→"杭州"）。如果无法确定则留空字符串。
- "keyword": 搜索品类关键词（如"咖啡厅"、"星巴克"、"水果超市"）。必须是单独的品类词，不要包含区域或修饰信息。
- "modifier": 修饰词，可能的值为"groupbuy"（团购相关）或null

注意：
1. 如果用户输入中包含"团购"、"优惠"、"套餐"等修饰词，modifier应设为"groupbuy"
2. 重要：如果modifier为"groupbuy"，不要将"团购"直接作为keyword的一部分！例如"水果团购" -> keyword应为"水果店"或"水果超市"，modifier为"groupbuy"
3. 如果输入中包含"/"分隔符（如"上海闵行区/水果超市"），"/"前是区域，"/"后是品类
4. 如果输入包含多个区域或品类，取最明确的一个
5. 如果无法识别任何参数，将对应字段设为空字符串或null
6. 如果"团购"作为独立修饰词出现（如"带团购的水果店"），keyword应为"水果店"，modifier为"groupbuy"
7. **重要**：正确拆分区域！如"杭州西湖区" -> region="西湖区", city="杭州"；"上海闵行区" -> region="闵行区", city="上海"；"北京" -> region="", city="北京"；"西湖区"（无城市信息）-> region="西湖区", city=""（因为无法确定城市）
8. **重要**：如果用户没有指定区县，只有城市名（如"北京"、"杭州"），将region设为""，city设为城市名

输出示例：
{"region": "海淀区", "city": "北京", "keyword": "星巴克", "modifier": null}
{"region": "闵行区", "city": "上海", "keyword": "水果店", "modifier": "groupbuy"}
{"region": "", "city": "深圳", "keyword": "咖啡厅", "modifier": null}
{"region": "西湖区", "city": "杭州", "keyword": "火锅", "modifier": null}"""


def _call_deepseek_intent(user_input: str) -> Dict[str, Any]:
    """
    调用DeepSeek解析用户意图。

    参数：
        user_input: 用户的自然语言输入

    返回：
        解析后的参数字典，包含 region、keyword、modifier

    抛出：
        RuntimeError: API调用失败或解析结果无效时
    """
    client = OpenAI(
        base_url=DEEPSEEK_BASE_URL,
        api_key=DEEPSEEK_API_KEY,
    )

    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ],
            temperature=0.1,
            max_tokens=256,
        )

        content = resp.choices[0].message.content.strip()
        logger.debug("DeepSeek返回: %s", content)

        # 尝试提取JSON（处理可能的markdown包装）
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            content = json_match.group()

        result = json.loads(content)

        # 验证必要字段
        result.setdefault("region", "")
        result.setdefault("city", "")
        result.setdefault("keyword", "")
        result.setdefault("modifier", None)

        return result

    except APIError as e:
        error_msg = f"DeepSeek API调用失败: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e
    except (json.JSONDecodeError, KeyError, AttributeError) as e:
        error_msg = f"DeepSeek返回解析失败: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


_REGION_PATTERN = re.compile(r'^[\u4e00-\u9fa5]{2,}(?:区|县|市|街道|镇|乡)$')


def _validate_region(region: str) -> bool:
    """校验 region 格式：2字以上中文，以区/县/市/街道/镇/乡结尾"""
    return bool(_REGION_PATTERN.match(region))


def _check_missing_params(intent: Dict[str, Any]) -> List[str]:
    """检查缺失的核心参数，返回缺失参数名的列表"""
    missing = []
    if not intent.get("region") and not intent.get("city"):
        missing.append("目标区域")
    if not intent.get("keyword"):
        missing.append("目标品类")
    return missing




def run(user_input: str) -> Dict[str, Any]:
    """
    Agent主入口：执行一次完整的商家信息抓取流程。

    流程：
    1. 意图解析（DeepSeek）
    2. 参数校验（缺失则追问）
    3. fetch_pois -> aggregate_and_clean -> parse_groupbuy_info -> export_to_table
    4. 结果汇报

    参数：
        user_input: 用户的自然语言输入

    返回：
        包含执行结果的字典：
        - success: bool
        - file_path: 生成文件的绝对路径（可选）
        - statistics: 统计数据（可选）
        - error: 错误信息（可选）
        - ask_for_input: 追问提示（可选）
    """
    # 验证配置
    try:
        validate_config()
    except RuntimeError as e:
        logger.error("配置验证失败: %s", e)
        return {"success": False, "error": str(e)}

    # 第一步：意图解析
    logger.info("意图解析: %s", user_input)
    print(f"[Agent] 正在解析您的输入: 「{user_input}」")

    try:
        intent = _call_deepseek_intent(user_input)
    except RuntimeError as e:
        return {"success": False, "error": str(e)}

    region = intent.get("region", "")
    keyword = intent.get("keyword", "")
    modifier = intent.get("modifier")

    logger.info("意图解析结果: region=%s, keyword=%s, modifier=%s", region, keyword, modifier)

    # 第二步：参数检查
    missing = _check_missing_params(intent)
    if missing:
        msg = f"请补充以下信息: {'、'.join(missing)}"
        logger.info("参数缺失: %s", msg)
        return {
            "success": False,
            "ask_for_input": msg,
        }

    # 判断场景
    is_scene_b = (modifier == "groupbuy")
    if is_scene_b:
        print(f"[Agent] 检测到团购需求，将以「{keyword}」为关键词搜索，并过滤出支持团购的商家")

    # 第三步：执行主流程
    try:
        city = intent.get("city", "")

        # 3.0 校验 region 格式，不符合时降级到 city
        if region and not _validate_region(region):
            logger.warning("region 格式异常，降级到 city: region=%s -> city=%s", region, city)
            region = ""

        # 3.1 抓取POI数据
        search_region = region or city  # 有区县用区县，没有用城市

        if not search_region:
            # region 和 city 都为空，用 keyword 全图搜（不传 region）
            print(f"[Agent] 正在搜索「{keyword}」...")
            raw_pois = fetch_pois(
                api_key=AMAP_API_KEY,
                keyword=keyword,
                region="",
            )
        else:
            print(f"[Agent] 正在搜索区域「{search_region}」的「{keyword}」...")
            raw_pois = fetch_pois(
                api_key=AMAP_API_KEY,
                keyword=keyword,
                region=search_region,
            )

        # 3.1b 降级搜索：如果区县级搜索无结果但 city 存在，用 city 重试
        if not raw_pois and region and city:
            print(f"[Agent] 在「{region}」未找到结果，扩大范围至「{city}」搜索...")
            raw_pois = fetch_pois(
                api_key=AMAP_API_KEY,
                keyword=keyword,
                region=city,
            )
            if raw_pois:
                search_region = city
                print(f"[Agent] 已在「{city}」范围找到 {len(raw_pois)} 条结果")

        if not raw_pois:
            msg = f"在「{region}」未找到「{keyword}」相关商家"
            logger.warning(msg)
            return {
                "success": True,
                "statistics": {"total": 0},
                "result": msg,
                "intent": {"region": region, "keyword": keyword, "modifier": modifier},
            }

        # 3.2 数据清洗与聚合
        print(f"[Agent] 正在清洗和聚合数据（共 {len(raw_pois)} 条原始数据）...")
        cleaned_data = aggregate_and_clean(raw_pois, filter_groupbuy=is_scene_b)

        # 3.3 解析团购信息
        groupbuy_success = 0
        groupbuy_failed = 0

        print(f"[Agent] 正在解析各商家的团购信息（共 {len(cleaned_data)} 家）...")
        for idx, item in enumerate(cleaned_data):
            poi_id = item.get("id", "")
            detail_url = item.get("_detail_url", "")

            gb_result = parse_groupbuy_info(
                api_key=AMAP_API_KEY,
                poi_id=poi_id,
                detail_url=detail_url or None,
            )

            item["groupbuy"] = gb_result.get("groupbuy", "fetch_failed")
            item["groupbuy_url"] = gb_result.get("url", "")

            if gb_result.get("groupbuy") is True:
                groupbuy_success += 1
            elif gb_result.get("groupbuy") == "fetch_failed":
                groupbuy_failed += 1

            # 每10条打印一次进度
            if (idx + 1) % 10 == 0:
                print(f"[进度] 团购解析: {idx + 1}/{len(cleaned_data)}")

        print(f"[进度] 团购解析完成: 成功 {groupbuy_success} 家, 降级 {groupbuy_failed} 家")

        # 3.4 场景B：过滤无团购商家
        if is_scene_b:
            before_filter = len(cleaned_data)
            cleaned_data = apply_groupbuy_filter(cleaned_data)
            print(f"[Agent] 团购过滤完成: {before_filter} -> {len(cleaned_data)} 家")
            if not cleaned_data:
                msg = f"在「{region}」的「{keyword}」中未找到支持团购的商家"
                logger.info(msg)
                return {
                    "success": True,
                    "statistics": {"total": 0},
                    "result": msg,
                    "intent": {"region": region, "keyword": keyword, "modifier": modifier},
                }

        # 3.5 导出表格文件
        print("[Agent] 正在生成表格文件...")
        file_path = export_to_table(
            data=cleaned_data,
            region=region,
            keyword=keyword,
            fmt="csv",
        )

        # 第四步：统计汇报
        statistics = {
            "total": len(cleaned_data),
            "groupbuy_yes": groupbuy_success,
            "groupbuy_failed": groupbuy_failed,
            "filtered": is_scene_b,
        }

        logger.info("执行完成: 共 %d 条, 团购 %d 家, 降级 %d 家",
                     statistics["total"], statistics["groupbuy_yes"], statistics["groupbuy_failed"])

        result_msg = (
            f"\n{'='*50}\n"
            f"[OK] 抓取完成！\n"
            f"   - 目标区域: {region}\n"
            f"   - 搜索品类: {keyword}\n"
            f"   - 共获取: {statistics['total']} 家商家\n"
            f"   - 支持团购: {statistics['groupbuy_yes']} 家\n"
            f"   - 需人工核验: {statistics['groupbuy_failed']} 家\n"
            f"   - 文件保存至: {file_path}\n"
            f"{'='*50}"
        )
        print(result_msg)

        intent_info = {
            "region": region,
            "keyword": keyword,
            "modifier": modifier,
        }

        # 保存搜索记录
        try:
            save_search_history({
                "search_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_input": user_input,
                "region": region,
                "keyword": keyword,
                "modifier": modifier or "",
                "total": statistics["total"],
                "groupbuy_yes": statistics["groupbuy_yes"],
                "groupbuy_failed": statistics["groupbuy_failed"],
                "file_path": file_path,
            })
        except Exception as e:
            logger.warning("搜索记录保存失败（不影响主流程）: %s", e)

        return {
            "success": True,
            "file_path": file_path,
            "statistics": statistics,
            "result": result_msg,
            "intent": intent_info,
        }

    except RuntimeError as e:
        error_msg = str(e)
        logger.error("执行中断: %s", error_msg)
        print(f"[错误] {error_msg}")
        return {"success": False, "error": error_msg}
    except Exception as e:
        error_msg = f"执行过程中发生意外错误: {e}"
        logger.exception("未预期的错误")
        print(f"[错误] {error_msg}")
        return {"success": False, "error": error_msg}
