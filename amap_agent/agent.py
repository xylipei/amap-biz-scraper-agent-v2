"""
智能体编排模块 - DeepSeek意图解析与任务编排

职责：
- 调用DeepSeek API解析用户自然语言输入，提取区域、品类、修饰词
- 处理复合输入场景（场景A/B）
- 编排任务流程：fetch_pois -> aggregate_and_clean -> 团购标注(已停用网络检测) -> export_to_table
- 统计结果汇报

防跑偏要求（PRD 3.2）：
- 场景B：自动将"水果团购"修正为"水果店"/"水果超市";团购检测已停用（避免
  /place/detail ID 查询烧配额），场景B 结果统一标注"需人工核验(附链接)"
- 缺失核心参数时追问用户
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI, APIError

from amap_agent import config
from amap_agent.fetcher import (
    fetch_pois,
    fetch_pois_around,
    geocode_address,
    split_anchors,
    generate_grid_anchors,
)
from amap_agent.aggregator import aggregate_and_clean, apply_groupbuy_filter
from amap_agent.exporter import export_to_table, save_search_history
from amap_agent.districts import CITY_DISTRICTS

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
    # 禁用 httpx trust_env：本机默认行为 TLS 握手失败(ConnectError: EOF)，
    # trust_env=False 后走直连可正常访问 api.deepseek.com（已实测）
    import httpx
    client = OpenAI(
        base_url=DEEPSEEK_BASE_URL,
        api_key=config.DEEPSEEK_API_KEY,
        http_client=httpx.Client(trust_env=False),
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


_REGION_SUFFIX = ("区", "县", "镇", "乡", "街道")
_AROUND_WORDS = ("周边", "附近", "周围", "一带")
_GROUPBUY_WORDS = ("团购", "优惠", "套餐")


def _infer_city_from_region(region: str) -> str:
    """从区县级名称推断所属城市（基于内置区县表；"北京海淀区"取城市前缀）。"""
    for city in CITY_DISTRICTS:
        if region.startswith(city):
            return city
    for city, districts in CITY_DISTRICTS.items():
        if region in districts:
            return city
    return ""


def _split_region_city(area: str) -> Tuple[str, str]:
    """
    区域文本 → (region, city)，与 LLM 意图字段语义一致。

    - "北京海淀区" -> ("海淀区", "北京")
    - "海淀区"     -> ("海淀区", 反查城市或 "")
    - "南京"/"南京市" -> ("", "南京")（须在内置城市表内，表外回退 LLM）
    - 其他（如"南京站"具体地名）-> ("", "") 表示无法可靠判定
    """
    area = area.strip()
    if not area:
        return "", ""
    if area.endswith(_REGION_SUFFIX):
        region = area
        city = _infer_city_from_region(area)
        if city and region.startswith(city):
            rest = region[len(city):]
            rest = rest[1:] if rest.startswith("市") else rest
            if rest.endswith(_REGION_SUFFIX):
                region = rest
        return region, city
    city = area[:-1] if area.endswith("市") else area
    if city in CITY_DISTRICTS:
        return "", city
    return "", ""


def _parse_intent_rule_based(user_input: str) -> Optional[Dict[str, Any]]:
    """
    规则优先解析常见输入模式（第一性：输入本质是 区域/品类/修饰词 三元组）。

    保守原则：只覆盖最明确的模式（"/"分隔、区域+品类、周边模式）；
    需要常识映射（如"水果团购"→"水果店"）或区域无法可靠判定时返回 None，
    回退 DeepSeek，避免误判区域/品类造成搜索偏差。

    返回：
        与 _call_deepseek_intent 同结构的意图字典；无法可靠解析时返回 None
    """
    text = user_input.strip()
    if not text:
        return None

    around = any(w in text for w in _AROUND_WORDS)
    modifier = "groupbuy" if any(w in text for w in _GROUPBUY_WORDS) else None
    if modifier:
        # "水果团购"→"水果店"属常识映射，规则不做，交给 LLM
        return None

    keyword = ""
    region = ""
    city = ""
    anchor = ""

    if "/" in text:
        # 分隔符模式：区域/品类
        parts = [p.strip() for p in text.split("/") if p.strip()]
        if len(parts) != 2:
            return None
        area, keyword = parts
        if around:
            keyword = re.sub("|".join(_AROUND_WORDS), "", keyword).strip()
        if not keyword:
            return None
        region, city = _split_region_city(area)
        if not region and not city:
            return None
        anchor = area if around else ""
    elif around:
        # "地点 周边 品类" 或 "品类 附近 地点"（分隔词后允许空格）
        # 两模式都可能匹配同一输入，用「area 必须是合法地名(区县/城市)」消歧：
        # 品类词不会被识别为地名，误匹配自然淘汰；多候选取 area 更长者（更可能是完整地点）
        m_after = re.match(r"^(?P<area>.+?)[周边附近周围一带]+\s*(?P<kw>[\u4e00-\u9fa5A-Za-z0-9]+)$", text)
        m_before = re.match(r"^(?P<kw>[\u4e00-\u9fa5A-Za-z0-9]+)\s*[周边附近周围一带]+(?P<area>.+)$", text)
        candidates = []
        if m_after:
            r, c = _split_region_city(m_after.group("area").strip())
            if r or c:
                candidates.append((m_after, r, c))
        if m_before:
            r, c = _split_region_city(m_before.group("area").strip())
            if r or c:
                candidates.append((m_before, r, c))
        if not candidates:
            return None
        m, region, city = max(candidates, key=lambda x: len(x[0].group("area")))
        area = m.group("area").strip()
        keyword = m.group("kw")
        anchor = area
        if not region and not city:
            return None
    else:
        # "区域 品类"：最后一段为品类，前面为区域
        tokens = text.split()
        if len(tokens) < 2:
            return None
        area = "".join(tokens[:-1])
        keyword = tokens[-1]
        region, city = _split_region_city(area)
        if not region and not city:
            return None

    if not keyword:
        return None
    return {
        "region": region,
        "city": city,
        "keyword": keyword,
        "modifier": modifier,
        "anchor": anchor,
        "around": around,
    }


def _check_missing_params(intent: Dict[str, Any]) -> List[str]:
    """检查缺失的核心参数，返回缺失参数名的列表"""
    missing = []
    if intent.get("around"):
        # 周边搜索模式：需要地点锚点 + 品类；锚点缺失但给出城市时自动网格铺点（D 方案）
        if not intent.get("anchor") and not intent.get("city"):
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

    print(f"[Agent] 周边搜索模式：围绕 {len(anchors)} 个地点搜索「{keyword}」(半径{config.AROUND_RADIUS}米)...")
    logger.info("周边搜索模式: anchors=%s, keyword=%s, city=%s", anchors, keyword, city)

    all_pois: List[Dict[str, Any]] = []
    for anchor in anchors:
        location = geocode_address(config.AMAP_API_KEY, anchor, city)
        if not location:
            print(f"[警告] 地点「{anchor}」无法解析为坐标，已跳过")
            logger.warning("地理编码失败，跳过锚点: %s", anchor)
            continue
        print(f"[Agent] 正在搜索「{anchor}」周边 {config.AROUND_RADIUS} 米内的「{keyword}」...")
        pois = fetch_pois_around(
            api_key=config.AMAP_API_KEY,
            location=location,
            keyword=keyword,
            radius=config.AROUND_RADIUS,
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


@dataclass
class FetchTask:
    """
    一个抓取单元（分片计划的组成部分，统一三种覆盖策略）。

    mode：
        "text"   - /place/text 搜索：region 为区县/行政区名（可为空=全国）
        "around" - /place/around 搜索：location 为文本锚点（执行时 geocode）
        "grid"   - 自动网格：以 city 为中心铺 (2N+1)x(2N+1) 圆心逐点 around
    """

    mode: str
    keyword: str = ""
    region: str = ""        # text 模式
    location: str = ""      # around 模式（文本锚点）
    city: str = ""          # grid 模式 / 展示用
    radius: int = 0          # around 模式半径
    label: str = ""         # 展示/导出文件名用


def build_fetch_plan(intent: Dict[str, Any]) -> List[FetchTask]:
    """
    意图 → 分片计划（统一区县拆分 B / 自动网格 D / 多锚点三种覆盖策略）。

    计划按执行顺序排列：基础通道（text）在前，周边通道（around/grid）在后；
    估算器（estimate_plan_requests）与执行器（execute_plan）共用同一份计划，
    保证“预估多少就执行多少”。

    参数：
        intent: 意图字典（region/city/keyword/around/anchor）

    返回：
        抓取单元列表（FetchTask）
    """
    keyword = intent.get("keyword", "")
    region = intent.get("region", "") or ""
    city = intent.get("city", "") or ""
    around = bool(intent.get("around"))
    anchor = intent.get("anchor", "") or ""
    districts = CITY_DISTRICTS.get(city) or []
    plan: List[FetchTask] = []

    if around:
        # 通道一：基础搜索（text）
        base_region = region or city
        if base_region:
            if not region and districts:
                # B 方案：城市级输入拆分逐区县（各区县独立 200 条）
                plan += [FetchTask("text", keyword=keyword, region=d, label=d) for d in districts]
            else:
                plan.append(FetchTask("text", keyword=keyword, region=base_region, label=base_region))
        # 通道二：周边搜索
        if anchor:
            # 多锚点：每个锚点一个 around 单元
            plan += [
                FetchTask("around", keyword=keyword, location=a,
                          radius=config.AROUND_RADIUS, label=a)
                for a in split_anchors(anchor)
            ]
        elif city:
            # D 方案：自动网格
            plan.append(FetchTask("grid", keyword=keyword, city=city, label=city))
    else:
        if region:
            plan.append(FetchTask("text", keyword=keyword, region=region, label=region))
        elif city and districts:
            # B 方案：城市级输入拆分逐区县
            plan += [FetchTask("text", keyword=keyword, region=d, label=d) for d in districts]
        else:
            plan.append(FetchTask("text", keyword=keyword, region="", label=""))
    return plan


def estimate_plan_requests(plan: List[FetchTask]) -> int:
    """
    分片计划 → 预估请求数（保守上限口径，与 execute_plan 一一对应）。

    - text：每单元 ≤10 页（200 条 / offset=20）
    - around：每单元 8 页 + 1 次 geocode（文本锚点需解析）
    - grid：每单元 (2N+1)² 圆心 × 8 页 + 1 次城市 geocode
    """
    grid_n = config.GRID_N
    total = 0
    for t in plan:
        if t.mode == "text":
            total += 10
        elif t.mode == "around":
            total += 8 + 1
        elif t.mode == "grid":
            total += (2 * grid_n + 1) ** 2 * 8 + 1
    return total


def format_plan_summary(plan: List[FetchTask]) -> str:
    """分片计划 → 人类可读摘要（覆盖策略预览，搜索前展示）。"""
    n_text = sum(1 for t in plan if t.mode == "text")
    n_around = sum(1 for t in plan if t.mode == "around")
    n_grid = sum(1 for t in plan if t.mode == "grid")
    parts = []
    if n_text:
        parts.append(f"{n_text} 个行政区/区县")
    if n_around:
        parts.append(f"{n_around} 个锚点")
    if n_grid:
        parts.append(f"{n_grid} 组网格（{(2 * config.GRID_N + 1) ** 2} 圆心/组）")
    return " + ".join(parts) if parts else "单次搜索"


def execute_plan(keyword: str, plan: List[FetchTask], city: str = "") -> Tuple[List[Dict[str, Any]], str]:
    """
    按分片计划执行抓取（保持顺序），合并去重。

    参数：
        keyword: 搜索品类关键词
        plan: build_fetch_plan 生成的分片计划
        city: 城市名（区县拆分时用作导出/展示标签，与旧行为一致）

    返回：
        (去重后的 POI 原始数据列表, 展示/导出用标签)
    """
    text_pois: List[Dict[str, Any]] = []
    around_pois: List[Dict[str, Any]] = []
    label = ""

    for t in plan:
        if t.mode == "text":
            if t.region:
                print(f"[Agent] 正在搜索区域「{t.region}」的「{t.keyword}」...")
            pois = fetch_pois(api_key=config.AMAP_API_KEY, keyword=t.keyword, region=t.region)
            if pois:
                print(f"[进度] 「{t.region or '全国'}」获取 {len(pois)} 条")
            else:
                print(f"[进度] 「{t.region or '全国'}」无结果")
            text_pois.extend(pois)
            if not label:
                label = t.label  # text 单元只记录首个标签(区县拆分时末尾统一为 city)
        elif t.mode == "around":
            pois, lab = _fetch_around_pois(t.keyword, t.location, t.city)
            around_pois.extend(pois)
            if lab:
                label = lab  # 周边锚点标签优先
        elif t.mode == "grid":
            pois, lab = _fetch_grid_around_pois(t.keyword, t.city)
            around_pois.extend(pois)
            if lab:
                label = lab  # 网格标签(城市名)优先

    # 去重（text 与 around 分别收集后统一合并）
    raw_pois = _merge_pois(text_pois, around_pois)
    if text_pois and around_pois and len(raw_pois) < len(text_pois) + len(around_pois):
        print(f"[进度] 双通道合并: 基础 {len(text_pois)} + 周边 {len(around_pois)} -> 去重 {len(raw_pois)} 条")
    elif text_pois and len(raw_pois) < len(text_pois):
        print(f"[进度] 跨区县去重: {len(text_pois)} -> {len(raw_pois)} 条")
    elif around_pois and len(raw_pois) < len(around_pois):
        print(f"[进度] 周边去重: {len(around_pois)} -> {len(raw_pois)} 条")

    # 展示/导出标签：优先周边标签；区县拆分(多 text 单元)且给 city 时统一用城市名
    text_tasks = [t for t in plan if t.mode == "text"]
    if len(text_tasks) > 1 and city:
        label = city
    elif not label and text_tasks:
        label = text_tasks[0].region or ""
    return raw_pois, label


def _fetch_grid_around_pois(
    keyword: str,
    city: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    自动网格周边搜索（D 方案）：以城市中心铺 (2N+1)x(2N+1) 网格圆心逐点搜索。

    高德对同一请求参数（同一圆心+半径）翻页最多 200 条；铺多个网格圆心
    逐点 /place/around 搜索，各圆心独立 200 条再合并去重。

    参数：
        keyword: 搜索品类关键词
        city: 城市名（用于地理编码取中心坐标）

    返回：
        (去重后的 POI 列表, 展示用标签)
    """
    center = geocode_address(config.AMAP_API_KEY, city)
    if not center:
        print(f"[警告] 城市「{city}」无法解析为坐标，自动网格跳过")
        return [], ""
    grid_anchors = generate_grid_anchors(center, config.GRID_RADIUS, config.GRID_N)
    print(f"[Agent] 自动网格：以「{city}」为中心生成 {len(grid_anchors)} 个网格圆心"
          f"（半径{config.AROUND_RADIUS}米，突破单请求 200 条上限）...")
    all_pois: List[Dict[str, Any]] = []
    for loc in grid_anchors:
        pois = fetch_pois_around(
            api_key=config.AMAP_API_KEY,
            location=loc,
            keyword=keyword,
            radius=config.AROUND_RADIUS,
        )
        if pois:
            print(f"[进度] 网格点 {loc} 获取 {len(pois)} 条")
        all_pois.extend(pois)
    if not all_pois:
        return [], city
    deduped = _merge_pois(all_pois)
    if len(deduped) != len(all_pois):
        print(f"[进度] 网格去重: {len(all_pois)} -> {len(deduped)} 条")
    return deduped, city


def _detect_groupbuy(cleaned_data: List[Dict[str, Any]]) -> Tuple[int, int]:
    """
    团购状态标注（已停用网络检测）。

    原实现逐店调用高德 /place/detail（ID 查询），单次搜索数千条 POI 即消耗
    数千次配额（实测一次搜索 4860 次直接打满日额度）。团购字段对业务非关键，
    已停用网络检测：统一标注 "fetch_failed"，表格显示"需人工核验(附链接)"。

    参数：
        cleaned_data: aggregate_and_clean 的输出列表（含 id / detail_url 内部字段）

    返回：
        (有团购商家数, 需人工核验商家数) —— 恒为 (0, len(cleaned_data))
    """
    total = len(cleaned_data)
    for item in cleaned_data:
        poi_id = item.get("id", "")
        detail_url = item.get("detail_url", "")
        # around 接口不返回 detail_url，按固定格式构造详情页 URL 供人工核验
        if not detail_url and poi_id:
            detail_url = f"https://ditu.amap.com/detail/{poi_id}"
            item["detail_url"] = detail_url
        item["groupbuy"] = "fetch_failed"
        item["groupbuy_url"] = detail_url

    if total:
        print(f"[Agent] 团购检测已停用：{total} 家商家统一标注「需人工核验(附链接)」")
    logger.info("团购检测（已停用）: %d 家商家统一标注 fetch_failed", total)
    return 0, total




def run_with_intent(intent: Dict[str, Any], user_input: str = "") -> Dict[str, Any]:
    """
    按已解析的结构化 intent 直接执行抓取流程（跳过 DeepSeek 意图解析）。

    供批量任务等输入已结构化的场景调用，避免为每个中心点重复调用 LLM；
    run() 内部同样复用本函数。

    参数：
        intent: 意图字典（region/city/keyword/modifier/anchor/around）
        user_input: 原始输入文本（用于搜索历史记录，可为空字符串）

    返回：
        同 run() 的结果字典
    """
    region = intent.get("region", "")
    keyword = intent.get("keyword", "")
    modifier = intent.get("modifier")

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

        # 3.0b 校验 region 格式，不符合时降级到 city
        if not around and region and not _validate_region(region):
            logger.warning("region 格式异常，降级到 city: region=%s -> city=%s", region, city)
            region = ""
            intent["region"] = ""

        # 分片计划：统一区县拆分(B)/自动网格(D)/多锚点覆盖策略，
        # 估算器与执行器共用同一份计划（预估多少就执行多少）
        plan = build_fetch_plan(intent)

        # 配额预算：搜索前估算并展示（第一性：配额即预算；剩余为 0 直接中止）
        try:
            from amap_agent.quota import quota_remaining, format_quota_summary

            estimate = estimate_plan_requests(plan)
            remaining = quota_remaining()
            if estimate:
                print(f"[Agent] ⚖️ 配额预估: {format_quota_summary(estimate)}")
                print(f"[Agent] 覆盖策略: {format_plan_summary(plan)}")
            if remaining <= 0:
                print("[错误] 高德API配额已用尽（本月剩余 0 次），已中止搜索。"
                      "请提高配额上限（企业认证 50000/月）或更换 Key。")
                return {"success": False, "error": "高德API配额已用尽，请提高配额上限或更换 Key"}
        except Exception as e:
            logger.warning("配额预算检查异常(不影响主流程): %s", e)

        # 3.0 执行分片计划（基础 text + 周边 around/grid，合并去重）
        raw_pois, anchor_label = execute_plan(keyword, plan, city)

        # 3.1b 降级搜索：区县/区域无结果但 city 存在，扩大范围至 city 重试（非周边模式，保持原行为）
        if not raw_pois and not around and region and city:
            print(f"[Agent] 在「{region}」未找到结果，扩大范围至「{city}」搜索...")
            raw_pois = fetch_pois(
                api_key=config.AMAP_API_KEY,
                keyword=keyword,
                region=city,
            )
            if raw_pois:
                anchor_label = city
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
            fmt="xlsx",
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
            f"   - 搜索方式: 双通道（行政区基础搜索 + 周边搜索 半径{config.AROUND_RADIUS}米，已合并去重）\n"
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


def run(user_input: str) -> Dict[str, Any]:
    """
    Agent主入口：执行一次完整的商家信息抓取流程。

    流程：
    1. 意图解析（DeepSeek）
    2. 参数校验（缺失则追问）
    3. fetch_pois -> aggregate_and_clean -> 团购标注(已停用) -> export_to_table
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
        config.validate_config()
    except RuntimeError as e:
        logger.error("配置验证失败: %s", e)
        return {"success": False, "error": str(e)}

    # 第一步：意图解析（规则优先，DeepSeek 兜底——第一性：输入本质是 区域/品类/修饰词 三元组）
    logger.info("意图解析: %s", user_input)
    print(f"[Agent] 正在解析您的输入: 「{user_input}」")

    try:
        intent = _parse_intent_rule_based(user_input)
        if intent:
            logger.info("规则解析命中: %s", intent)
        else:
            print("[Agent] 规则无法可靠解析，调用 DeepSeek 兜底...")
            intent = _call_deepseek_intent(user_input)
    except RuntimeError as e:
        return {"success": False, "error": str(e)}

    # 兜底修正：输入含周边意图词（周边/附近/周围/一带）但 DeepSeek 漏判 around 时，
    # 用 region（行政区）作为周边中心锚点，确保双通道搜索生效
    if (not intent.get("around")) and re.search(r"周边|附近|周围|一带", user_input):
        if not intent.get("anchor") and intent.get("region"):
            logger.warning("意图解析漏判周边模式，兜底修正: anchor=%s, around=True", intent["region"])
            intent["anchor"] = intent["region"]
            intent["around"] = True

    return run_with_intent(intent, user_input=user_input)
