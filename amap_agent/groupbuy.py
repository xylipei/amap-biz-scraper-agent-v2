"""
团购信息解析模块 - 判断商家是否支持团购

职责：
- 优先调用高德详情页接口解析团购信息
- 若遇反爬限制或数据不可用，降级返回URL
- 必须捕获所有异常，不得因单个门店导致程序崩溃

防跑偏要求（PRD 4.1）：
- HTTP 403/IP封禁 -> 捕获异常，返回 {"groupbuy": "fetch_failed", "url": detail_url}
- 任何异常不得使程序崩溃
"""

import logging
import re
from typing import Any, Dict, Optional

import requests

from amap_agent.config import PLACE_DETAIL_URL

logger = logging.getLogger(__name__)

# 团购相关关键词（正则匹配用）
GROUPBUY_PATTERNS = [
    re.compile(r"团购", re.IGNORECASE),
    re.compile(r"优惠", re.IGNORECASE),
    re.compile(r"套餐", re.IGNORECASE),
    re.compile(r"代金券", re.IGNORECASE),
    re.compile(r"group.?buy", re.IGNORECASE),
    re.compile(r"coupon", re.IGNORECASE),
]


def _check_groupbuy_via_detail_api(api_key: str, poi_id: str) -> Optional[bool]:
    """
    通过高德 /place/detail 接口检查团购信息。

    参数：
        api_key: 高德API Key
        poi_id: POI的唯一ID

    返回：
        True/False 表示是否有团购，None 表示无法判断
    """
    try:
        params = {
            "key": api_key,
            "id": poi_id,
        }
        resp = requests.get(PLACE_DETAIL_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "1":
            logger.debug("detail API返回异常: %s", data.get("info", ""))
            return None

        pois = data.get("pois", [])
        if not pois:
            return None

        poi = pois[0]

        # 检查 biz_ext 中的团购信息
        biz_ext = poi.get("biz_ext", {}) or {}
        if biz_ext.get("groupbuy") or biz_ext.get("coupon"):
            return True

        # 检查 deep_info
        deep_info = poi.get("deep_info", {}) or {}
        if deep_info.get("groupbuy") or deep_info.get("is_group_buy") == "1":
            return True

        # 检查 photos 等字段中是否提及
        photos = poi.get("photos", []) or []
        for photo in photos:
            title = photo.get("title", "") or ""
            for pattern in GROUPBUY_PATTERNS:
                if pattern.search(title):
                    return True

        return False

    except requests.exceptions.RequestException as e:
        logger.warning("detail API请求失败 (poi_id=%s): %s", poi_id, e)
        return None
    except (KeyError, ValueError, TypeError) as e:
        logger.warning("detail API解析异常 (poi_id=%s): %s", poi_id, e)
        return None


def _check_groupbuy_via_h5(detail_url: str) -> Optional[bool]:
    """
    通过高德H5详情页检查团购信息。

    参数：
        detail_url: 高德商户详情页URL

    返回：
        True/False 表示是否有团购，None 表示无法判断
    """
    if not detail_url:
        return None

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        resp = requests.get(detail_url, headers=headers, timeout=10)

        if resp.status_code == 403:
            logger.warning("H5详情页反爬触发 (status=403), url=%s", detail_url)
            return None  # 反爬触发，降级

        resp.raise_for_status()

        # 在页面内容中搜索团购关键词
        text = resp.text
        for pattern in GROUPBUY_PATTERNS:
            if pattern.search(text):
                logger.debug("H5页面检测到团购关键词, url=%s", detail_url)
                return True

        return False

    except requests.exceptions.RequestException as e:
        logger.warning("H5详情页请求失败 (url=%s): %s", detail_url, e)
        return None


def parse_groupbuy_info(
    api_key: str,
    poi_id: str,
    detail_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    解析门店的团购信息。

    优先级：
    1. 调用高德 /place/detail API 检查团购
    2. 若API无数据，尝试HTTP抓取H5详情页
    3. 全部失败 -> 降级返回 fetch_failed + url

    参数：
        api_key: 高德API Key
        poi_id: POI唯一ID
        detail_url: 商户高德详情页URL（可选）

    返回：
        字典，格式为：
        - 成功: {"groupbuy": True/False, "url": detail_url}
        - 降级: {"groupbuy": "fetch_failed", "url": detail_url}
        - 反爬: {"groupbuy": "fetch_failed", "url": detail_url}
    """
    result: Dict[str, Any] = {
        "groupbuy": "fetch_failed",
        "url": detail_url or "",
    }

    # 无poi_id，无法通过API判断，直接尝试H5
    if not poi_id:
        h5_result = _check_groupbuy_via_h5(detail_url or "")
        if h5_result is not None:
            result["groupbuy"] = h5_result
        return result

    # 第一步：尝试 detail API
    api_result = _check_groupbuy_via_detail_api(api_key, poi_id)
    if api_result is not None:
        result["groupbuy"] = api_result
        logger.debug("团购解析成功 (poi_id=%s): %s", poi_id, api_result)
        return result

    # 第二步：API无法判断，尝试H5详情页
    if detail_url:
        h5_result = _check_groupbuy_via_h5(detail_url)
        if h5_result is not None:
            result["groupbuy"] = h5_result
            logger.debug("团购解析成功(H5) (poi_id=%s): %s", poi_id, h5_result)
            return result

    # 第三步：全部失败，降级
    logger.warning("团购解析失败，已降级 (poi_id=%s, url=%s)", poi_id, detail_url)
    result["groupbuy"] = "fetch_failed"
    result["url"] = detail_url or ""
    return result
