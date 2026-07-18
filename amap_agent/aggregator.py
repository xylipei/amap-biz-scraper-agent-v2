"""
数据聚合与清洗模块 - 统计同名门店数量、过滤冗余字段

职责：
- 清洗原始JSON数据，提取统一结构字段
- 统计同名门店数量
- 按团购字段过滤（场景B逻辑）
- 处理空值，确保输出字典结构一致

防跑偏要求（PRD 4.1）：
- 处理空值，确保输出字典结构一致
- 若触发了场景B逻辑，根据团购字段过滤无效数据
"""

import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _extract_field(poi: Dict[str, Any], field: str, default: str = "") -> str:
    """安全提取POI字段，处理None值"""
    value = poi.get(field)
    if value is None:
        return default
    return str(value).strip()


def _extract_base_name(name: str) -> str:
    """
    从完整店名中提取品牌基础名（括号前的部分）。

    用于同名门店聚合计数：
    "鲜丰水果(上海荣顺苑店)" -> "鲜丰水果"
    "百果园(莘建路店)"       -> "百果园"
    "星巴克"                 -> "星巴克"  # 无括号不处理
    """
    import re
    match = re.match(r'^(.+?)[（(]', name)
    if match:
        return match.group(1).strip()
    return name.strip()


def aggregate_and_clean(
    raw_pois_list: List[Dict[str, Any]],
    filter_groupbuy: bool = False,
) -> List[Dict[str, Any]]:
    """
    清洗原始POI数据，统计同名门店数量。

    参数：
        raw_pois_list: fetch_pois 返回的原始POI数据列表
        filter_groupbuy: 是否过滤掉无团购的商家（场景B逻辑）

    返回：
        统一结构的字典列表，每个字典包含以下字段：
        - name: 门店名称
        - address: 地址
        - location: 经纬度
        - pname: 省份
        - cityname: 城市
        - adname: 区县
        - tel: 电话
        - same_name_count: 同名门店数量
        - adcode: 区域代码
        - type: POI类型
        - groupbuy: 团购状态（由groupbuy模块填充）
        - groupbuy_url: 团购详情页URL（由groupbuy模块填充）
        - collect_year: 收录年份（始终填N/A）
    """
    if not raw_pois_list:
        logger.info("原始POI列表为空，返回空结果")
        return []

    # 第一步：提取统一字段
    cleaned_list: List[Dict[str, Any]] = []
    for poi in raw_pois_list:
        cleaned_item = {
            "name": _extract_field(poi, "name"),
            "address": _extract_field(poi, "address"),
            "location": _extract_field(poi, "location"),
            "pname": _extract_field(poi, "pname"),
            "cityname": _extract_field(poi, "cityname"),
            "adname": _extract_field(poi, "adname"),
            "tel": _extract_field(poi, "tel"),
            "type": _extract_field(poi, "type"),
            "adcode": _extract_field(poi, "adcode"),
            "id": _extract_field(poi, "id"),
            # 以下字段后续由 groupbuy 模块和本模块填充
            "same_name_count": 0,
            "groupbuy": "",
            "groupbuy_url": "",
            "collect_year": "N/A",  # 高德API不提供收录年份，固定填N/A
            # 保留原始detail_url供groupbuy模块使用
            "_detail_url": _extract_field(poi, "detail"),
        }
        cleaned_list.append(cleaned_item)

    # 第二步：统计同名门店数量（按品牌基础名聚合）
    for item in cleaned_list:
        if item["name"]:
            item["_base_name"] = _extract_base_name(item["name"])
        else:
            item["_base_name"] = ""

    name_counter = Counter(
        item["_base_name"] for item in cleaned_list if item["_base_name"]
    )

    for item in cleaned_list:
        if item["_base_name"]:
            item["same_name_count"] = name_counter[item["_base_name"]]
        item.pop("_base_name", None)

    # 第三步：场景B - 团购过滤
    if filter_groupbuy:
        before_count = len(cleaned_list)
        # 只保留 groupbuy 为 True 的商家
        # （注意：此时 groupbuy 字段尚未填充，过滤逻辑由 agent 编排层在调用后处理）
        # 此处标记后续需要执行过滤
        logger.info(
            "场景B逻辑已标记：filter_groupbuy=True，后续需移除无团购商家"
        )

    logger.info(
        "数据清洗完成: 原始 %d 条 -> 清洗后 %d 条，同名统计已生成",
        len(raw_pois_list),
        len(cleaned_list),
    )
    return cleaned_list


def apply_groupbuy_filter(
    cleaned_data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    场景B：根据团购字段过滤，仅保留明确有团购的商家。

    过滤规则：
    - groupbuy=True -> 保留
    - groupbuy="fetch_failed" -> 保留（标注"需人工核验"）
    - groupbuy=False / "" -> 剔除

    参数：
        cleaned_data: 已经过团购解析的数据列表

    返回：
        过滤后的数据列表
    """
    total_before = len(cleaned_data)
    has_groupbuy = 0
    fetch_failed = 0

    filtered = []
    for item in cleaned_data:
        gb = item.get("groupbuy")
        if gb is True:
            filtered.append(item)
            has_groupbuy += 1
        elif gb == "fetch_failed":
            # 降级处理：保留但标记需人工核验
            item["groupbuy"] = "需人工核验"
            filtered.append(item)
            fetch_failed += 1
        # groupbuy=False 或 "" -> 剔除

    total_after = len(filtered)
    logger.info(
        "团购过滤完成: 过滤前 %d 条 -> 过滤后 %d 条 (有团购 %d, 降级 %d)",
        total_before,
        total_after,
        has_groupbuy,
        fetch_failed,
    )
    return filtered
