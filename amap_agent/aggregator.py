"""
数据聚合与清洗模块 - 统计同名门店数量、过滤冗余字段

职责：
- 清洗原始JSON数据，提取统一结构字段
- 统计同名门店数量
- 处理空值，确保输出字典结构一致

防跑偏要求（PRD 4.1）：
- 处理空值，确保输出字典结构一致
"""

import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 高德返回的无效占位值（统一清洗为空串）
_INVALID_VALUES = ("", "[]", "null", "None", "none", "NaN")


def _clean_str(value: str) -> str:
    """清洗字段值：去掉首尾空白，无效占位值（[]/null/None 等）统一转为空串"""
    v = value.strip()
    if v in _INVALID_VALUES:
        return ""
    return v


def _extract_field(poi: Dict[str, Any], field: str, default: str = "") -> str:
    """安全提取POI字段，处理None值，并清洗无效占位值"""
    value = poi.get(field)
    if value is None:
        return default
    return _clean_str(str(value))


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


def _extract_rating(poi: Dict[str, Any]) -> str:
    """
    从 POI 原始数据中提取评分。

    高德搜索接口（extensions=all）返回的 biz_ext.rating 通常是字符串（如 "4.5"），
    但部分 POI 可能无 biz_ext 或 rating 为空。统一返回字符串，无评分时返回空串。
    """
    biz_ext = poi.get("biz_ext")
    if not isinstance(biz_ext, dict):
        return ""
    rating = biz_ext.get("rating")
    if rating is None:
        return ""
    # 过滤掉 "[]" 等无效占位值
    return _clean_str(str(rating))


def aggregate_and_clean(
    raw_pois_list: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    清洗原始POI数据，统计同名门店数量。

    参数：
        raw_pois_list: fetch_pois 返回的原始POI数据列表

    返回：
        统一结构的字典列表，每个字典包含以下字段：
        - name: 门店名称
        - same_name_count: 同名门店数量
        - collect_year: 高德收录年份（PRD 2.2：高德不提供，固定返回 "N/A"，禁止伪造）
        - pname: 省份
        - cityname: 城市
        - adname: 区县
        - address: 地址
        - tel: 电话
        - rating: 评分（来自高德 biz_ext.rating，可能为空）
        - type: POI类型
    """
    if not raw_pois_list:
        logger.info("原始POI列表为空，返回空结果")
        return []

    # 第一步：提取统一字段（门店名称含"炒货"/"花生"的直接过滤掉）
    EXCLUDE_KEYWORDS = ("炒货", "花生")
    cleaned_list: List[Dict[str, Any]] = []
    excluded_count = 0
    for poi in raw_pois_list:
        name = _extract_field(poi, "name")
        if any(kw in name for kw in EXCLUDE_KEYWORDS):
            excluded_count += 1
            continue
        cleaned_item = {
            "name": name,
            "same_name_count": 0,
            "collect_year": "N/A",  # PRD 2.2：高德不提供收录年份，禁止伪造
            "pname": _extract_field(poi, "pname"),
            "cityname": _extract_field(poi, "cityname"),
            "adname": _extract_field(poi, "adname"),
            "address": _extract_field(poi, "address"),
            "tel": _extract_field(poi, "tel"),
            "rating": _extract_rating(poi),
            "type": _extract_field(poi, "type"),
            # 内部字段（不导出）
            "adcode": _extract_field(poi, "adcode"),
            "id": _extract_field(poi, "id"),
        }
        cleaned_list.append(cleaned_item)

    if excluded_count:
        logger.info("已过滤含 %s 的门店 %d 条", EXCLUDE_KEYWORDS, excluded_count)

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

    logger.info(
        "数据清洗完成: 原始 %d 条 -> 清洗后 %d 条，同名统计已生成",
        len(raw_pois_list),
        len(cleaned_list),
    )
    return cleaned_list
