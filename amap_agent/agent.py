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
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI, APIError

from amap_agent.config import (
    AMAP_API_KEY,
    DEEPSEEK_API_KEY,
    AROUND_RADIUS,
    validate_config,
)
from amap_agent.fetcher import fetch_pois, fetch_pois_around, geocode_address, split_anchors
from amap_agent.aggregator import aggregate_and_clean, apply_groupbuy_filter
from amap_agent.groupbuy import parse_groupbuy_info
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
- "anchor": **地点锚点**，周边搜索的中心地点。当用户输入包含"周边"、"附近"、"周围"、"一带"等词，或给出一个具体地点/建筑/机构名并要求搜索该地点周围的商家时，将该地点完整填入（如"南京市鼓楼区政府大楼"、"南京站"、"西湖"）。注意：anchor 是完整的地点描述，可以带城市前缀，与 region（区县级）不同。没有周边搜索意图时填空字符串。
- "around": 布尔值，是否为周边搜索模式。当 anchor 非空（即用户想搜某地点周边的商家）时为 true，否则为 false。

注意：
1. 如果用户输入中包含"团购"、"优惠"、"套餐"等修饰词，modifier应设为"groupbuy"
2. 重要：如果modifier为"groupbuy"，不要将"团购"直接作为keyword的一部分！例如"水果团购" -> keyword应为"水果店"或"水果超市"，modifier为"groupbuy"
3. 如果输入中包含"/"分隔符（如"上海闵行区/水果超市"），"/"前是区域，"/"后是品类
4. 如果输入包含多个区域或品类，取最明确的一个
5. 如果无法识别任何参数，将对应字段设为空字符串或null
6. 如果"团购"作为独立修饰词出现（如"带团购的水果店"），keyword应为"水果店"，modifier为"groupbuy"
7. **重要**：正确拆分区域！如"杭州西湖区" -> region="西湖区", city="杭州"；"上海闵行区" -> region="闵行区", city="上海"；"北京" -> region="", city="北京"；"西湖区"（无城市信息）-> region="西湖区", city=""（因为无法确定城市）
8. **重要**：如果用户没有指定区县，只有城市名（如"北京"、"杭州"），将region设为""，city设为城市名
9. **重要**：周边搜索模式！**只要输入中出现"周边"、"附近"、"周围"、"一带"等词，around 必须为 true（强规则，即使地点是行政区名也要遵守）**。示例："南京市鼓楼区 周边 水果商超" -> anchor="南京市鼓楼区", around=true, keyword="水果商超"；"水果商超 附近 南京市政府大楼" -> anchor="南京市政府大楼", around=true。将"周边/附近"等词指向的地点完整填入anchor（行政区名也要填入anchor），region可同时保留区县名，city填城市以帮助地理编码。多地点锚点（用顿号、逗号、"和"连接）整体放入anchor字段，如"南京市政府大楼、南京站"。
10. 周边搜索模式下，如果地点中能识别出城市（如"南京市鼓楼区政府大楼"→南京），city应填"南京"以帮助地理编码收窄范围。

输出示例：
{"region": "海淀区", "city": "北京", "keyword": "星巴克", "modifier": null, "anchor": "", "around": false}
{"region": "闵行区", "city": "上海", "keyword": "水果店", "modifier": "groupbuy", "anchor": "", "around": false}
{"region": "", "city": "深圳", "keyword": "咖啡厅", "modifier": null, "anchor": "", "around": false}
{"region": "西湖区", "city": "杭州", "keyword": "火锅", "modifier": null, "anchor": "", "around": false}
{"region": "", "city": "南京", "keyword": "水果商超", "modifier": null, "anchor": "南京市鼓楼区政府大楼", "around": true}
{"region": "鼓楼区", "city": "南京", "keyword": "水果商超", "modifier": null, "anchor": "南京市鼓楼区", "around": true}
{"region": "", "city": "南京", "keyword": "水果商超", "modifier": null, "anchor": "南京市政府大楼、南京站", "around": true}"""


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
        result.setdefault("anchor", "")
        result.setdefault("around", False)

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
    if intent.get("around"):
        # 周边搜索模式：需要地点锚点 + 品类
        if not intent.get("anchor"):
            missing.append("地点锚点")
        if not intent.get("keyword"):
            missing.append("目标品类")
    else:
        # 常规模式：需要区域 + 品类
        if not intent.get("region") and not intent.get("city"):
            missing.append("目标区域")
        if not intent.get("keyword"):
            missing.append("目标品类")
    return missing


def _merge_pois(*poi_lists: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    多通道结果合并去重：按 poi id 去重，保持传入顺序（先基础后周边）。

    参数：
        poi_lists: 一个或多个 POI 原始数据列表

    返回：
        去重后的 POI 列表
    """
    seen: set = set()
    merged: List[Dict[str, Any]] = []
    for pois in poi_lists:
        for p in pois:
            pid = p.get("id", "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            merged.append(p)
    return merged


def _fetch_around_pois(
    keyword: str,
    anchor_text: str,
    city: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    周边搜索模式：对每个地点锚点做地理编码 + 周边搜索，按 poi id 去重合并。

    参数：
        keyword: 搜索品类关键词
        anchor_text: 地点锚点原文（可含多个地点，用顿号/逗号/和连接）
        city: 城市名（用于收窄地理编码范围，可为空）

    返回：
        (去重后的 POI 列表, 展示用锚点名)
    """
    anchors = split_anchors(anchor_text)
    if not anchors:
        return [], ""

    print(f"[Agent] 周边搜索模式：围绕 {len(anchors)} 个地点搜索「{keyword}」(半径{AROUND_RADIUS}米)...")
    logger.info("周边搜索模式: anchors=%s, keyword=%s, city=%s", anchors, keyword, city)

    all_pois: List[Dict[str, Any]] = []
    for anchor in anchors:
        location = geocode_address(AMAP_API_KEY, anchor, city)
        if not location:
            print(f"[警告] 地点「{anchor}」无法解析为坐标，已跳过")
            logger.warning("地理编码失败，跳过锚点: %s", anchor)
            continue
        print(f"[Agent] 正在搜索「{anchor}」周边 {AROUND_RADIUS} 米内的「{keyword}」...")
        pois = fetch_pois_around(
            api_key=AMAP_API_KEY,
            location=location,
            keyword=keyword,
            radius=AROUND_RADIUS,
        )
        all_pois.extend(pois)

    if not all_pois:
        return [], anchors[0]

    # 多锚点去重（同一 poi id 只保留一条，复用 _merge_pois）
    deduped = _merge_pois(all_pois)

    if len(deduped) != len(all_pois):
        logger.info("多锚点去重: %d -> %d 条", len(all_pois), len(deduped))
        print(f"[进度] 多锚点去重: {len(all_pois)} -> {len(deduped)} 条")

    return deduped, anchors[0]


def _detect_groupbuy(cleaned_data: List[Dict[str, Any]]) -> Tuple[int, int]:
    """
    对每条商家数据检测团购状态（PRD 2.2：填充"是否团购"字段）。

    优先调用高德 /place/detail API，失败时降级 H5 详情页，
    单条失败不影响整体流程（parse_groupbuy_info 内部已全捕获）。

    参数：
        cleaned_data: aggregate_and_clean 的输出列表（含 id / detail_url 内部字段）

    返回：
        (有团购商家数, 降级/需人工核验商家数)
    """
    total = len(cleaned_data)
    if not total:
        return 0, 0

    print(f"[Agent] 正在检测 {total} 家商家的团购状态...")
    groupbuy_count = 0
    fetch_failed_count = 0

    for idx, item in enumerate(cleaned_data, 1):
        poi_id = item.get("id", "")
        detail_url = item.get("detail_url", "")
        # around 接口不返回 detail_url，按固定格式构造详情页 URL 供核验/H5 降级
        if not detail_url and poi_id:
            detail_url = f"https://ditu.amap.com/detail/{poi_id}"
            item["detail_url"] = detail_url
        try:
            result = parse_groupbuy_info(AMAP_API_KEY, poi_id, detail_url)
        except Exception as e:
            # 单条兜底：检测异常不中断整体流程
            logger.warning("团购检测异常 (id=%s): %s", poi_id, e)
            result = {"groupbuy": "fetch_failed", "url": detail_url}
        item["groupbuy"] = result.get("groupbuy", "fetch_failed")
        item["groupbuy_url"] = result.get("url", detail_url)

        if item["groupbuy"] is True:
            groupbuy_count += 1
        elif item["groupbuy"] == "fetch_failed":
            fetch_failed_count += 1

        if idx % 10 == 0 or idx == total:
            print(f"[进度] 团购检测 {idx}/{total} (有团购 {groupbuy_count}, 需核验 {fetch_failed_count})")

        # 节流：detail API QPS 限制严格（实测 >2 QPS 触发 CUQPS），
        # 调用间至少间隔 0.5s（H5 路径本身较慢，额外 sleep 影响可忽略）
        if idx != total:
            time.sleep(0.5)

    no_groupbuy = total - groupbuy_count - fetch_failed_count
    logger.info("团购检测完成: 有团购 %d 家, 无团购 %d 家, 需人工核验 %d 家",
                groupbuy_count, no_groupbuy, fetch_failed_count)
    return groupbuy_count, fetch_failed_count




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

    # 兜底修正：输入含周边意图词（周边/附近/周围/一带）但 DeepSeek 漏判 around 时，
    # 用 region（行政区）作为周边中心锚点，确保双通道搜索生效
    if (not intent.get("around")) and re.search(r"周边|附近|周围|一带", user_input):
        if not intent.get("anchor") and intent.get("region"):
            logger.warning("意图解析漏判周边模式，兜底修正: anchor=%s, around=True", intent["region"])
            intent["anchor"] = intent["region"]
            intent["around"] = True
            region = intent.get("region", "")

    logger.info("意图解析结果: region=%s, keyword=%s, modifier=%s, anchor=%s, around=%s",
                region, keyword, modifier, intent.get("anchor", ""), intent.get("around", False))

    # 第二步：参数检查
    missing = _check_missing_params(intent)
    if missing:
        msg = f"请补充以下信息: {'、'.join(missing)}"
        logger.info("参数缺失: %s", msg)
        return {
            "success": False,
            "ask_for_input": msg,
        }

    # 第三步：执行主流程
    try:
        city = intent.get("city", "")
        anchor_text = intent.get("anchor", "")
        around = bool(intent.get("around"))
        anchor_label = ""

        if around and anchor_text:
            # 3.0 双通道搜索（先基础后周边，合并去重，缓解单通道 200 条上限）
            # 通道一：基础搜索（行政区/城市 /place/text，先执行）
            base_region = region or city
            base_pois: List[Dict[str, Any]] = []
            if base_region:
                print(f"[Agent] 通道一（基础搜索）：正在搜索区域「{base_region}」的「{keyword}」...")
                base_pois = fetch_pois(
                    api_key=AMAP_API_KEY,
                    keyword=keyword,
                    region=base_region,
                )
                if base_pois:
                    print(f"[Agent] 基础搜索完成: 共 {len(base_pois)} 条")

            # 通道二：周边搜索（多锚点地理编码 + 周边搜索 + 去重）
            around_pois, anchor_label = _fetch_around_pois(keyword, anchor_text, city)

            # 合并去重（先基础后周边）
            raw_pois = _merge_pois(base_pois, around_pois)
            if base_pois and around_pois and len(raw_pois) < len(base_pois) + len(around_pois):
                print(f"[进度] 双通道合并: 基础 {len(base_pois)} + 周边 {len(around_pois)} -> 去重 {len(raw_pois)} 条")
        else:
            # 3.0b 校验 region 格式，不符合时降级到 city
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
            msg = f"在「{anchor_label or region}」未找到「{keyword}」相关商家"
            logger.warning(msg)
            return {
                "success": True,
                "statistics": {"total": 0},
                "result": msg,
                "intent": {
                    "region": region,
                    "keyword": keyword,
                    "modifier": modifier,
                    "anchor": anchor_text,
                    "around": around,
                },
            }

        # 3.2 数据清洗与聚合
        print(f"[Agent] 正在清洗和聚合数据（共 {len(raw_pois)} 条原始数据）...")
        cleaned_data = aggregate_and_clean(raw_pois)

        # 3.3 团购检测（PRD 2.2：填充"是否团购"字段，所有场景均检测）
        groupbuy_count, fetch_failed_count = _detect_groupbuy(cleaned_data)

        # 3.3b 场景B强制过滤（PRD 3.2）：modifier=groupbuy 时剔除无团购商家
        if modifier == "groupbuy":
            before_count = len(cleaned_data)
            cleaned_data = apply_groupbuy_filter(cleaned_data)
            print(f"[Agent] 场景B过滤: {before_count} -> {len(cleaned_data)} 家（已剔除无团购商家）")

        # 3.3c 统计有评分的商家数
        rating_count = sum(1 for item in cleaned_data if item.get("rating"))
        print(f"[进度] 数据清洗完成: 共 {len(cleaned_data)} 家, 其中有评分 {rating_count} 家")

        # 3.4 导出表格文件
        print("[Agent] 正在生成表格文件...")
        file_path = export_to_table(
            data=cleaned_data,
            region=anchor_label or region,
            keyword=keyword,
            fmt="csv",
        )

        # 第四步：统计汇报
        statistics = {
            "total": len(cleaned_data),
            "rating_count": rating_count,
            "groupbuy_count": groupbuy_count,
            "fetch_failed_count": fetch_failed_count,
        }

        logger.info("执行完成: 共 %d 条, 有评分 %d 家, 有团购 %d 家, 需核验 %d 家",
                     statistics["total"], statistics["rating_count"],
                     groupbuy_count, fetch_failed_count)

        search_mode_desc = (
            f"   - 搜索方式: 双通道（行政区基础搜索 + 周边搜索 半径{AROUND_RADIUS}米，已合并去重）\n"
            if around and anchor_label else ""
        )
        result_msg = (
            f"\n{'='*50}\n"
            f"[OK] 抓取完成！\n"
            f"   - 目标区域: {anchor_label or region}\n"
            f"   - 搜索品类: {keyword}\n"
            f"{search_mode_desc}"
            f"   - 共获取: {statistics['total']} 家商家\n"
            f"   - 其中有评分: {statistics['rating_count']} 家\n"
            f"   - 有团购商家: {groupbuy_count} 家\n"
            f"   - 需人工核验: {fetch_failed_count} 家\n"
            f"   - 文件保存至: {file_path}\n"
            f"{'='*50}"
        )
        print(result_msg)

        intent_info = {
            "region": region,
            "keyword": keyword,
            "modifier": modifier,
            "anchor": anchor_text,
            "around": around,
        }

        # 保存搜索记录
        try:
            save_search_history({
                "search_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_input": user_input,
                "region": anchor_label or region,
                "keyword": keyword,
                "modifier": modifier or "",
                "total": statistics["total"],
                "rating_count": statistics["rating_count"],
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
