"""
POI数据抓取模块 - 调用高德地图API获取商家信息

职责：
- 调用高德 /place/text 或 /place/polygon 接口
- 实现分页机制（循环调用直至无数据）
- 实现重试机制（网络超时重试3次，指数退避）
- 实现QPS控制（每次请求间隔200ms）
- 检测API配额超限（错误码 10003/10044）

防跑偏要求（PRD 4.1）：
1. 必须实现分页循环
2. 必须包含重试机制（3次）
3. 必须包含QPS控制（200ms间隔）
4. 配额超限时立即终止
"""

import time
import logging
from typing import Any, Dict, List, Optional

import requests

from amap_agent.config import (
    PLACE_TEXT_URL,
    PLACE_AROUND_URL,
    GEOCODE_URL,
    REQUEST_INTERVAL,
    MAX_RETRIES,
    PAGE_SIZE,
    AROUND_RADIUS,
    AROUND_PAGE_SIZE,
    GRID_RADIUS,
    GRID_N,
    ERR_QUOTA_EXCEEDED,
)

logger = logging.getLogger(__name__)

# 地理编码 level 优先级（数值越小越精确，用于多个候选结果时消解歧义）
_GEOCODE_LEVEL_PRIORITY = {
    "兴趣点": 1,
    "门牌号": 2,
    "道路": 3,
    "乡镇": 4,
    "街道": 5,
    "区县": 6,
    "市": 7,
    "城市": 7,
    "省": 8,
    "省份": 8,
}


def _request_with_retry(url: str, params: Dict[str, Any], retries: int = MAX_RETRIES) -> Dict[str, Any]:
    """
    带重试机制的HTTP GET请求。

    参数：
        url: 请求URL
        params: 查询参数字典
        retries: 最大重试次数

    返回：
        解析后的JSON字典

    抛出：
        RuntimeError: 配额超限或所有重试耗尽
    """
    from amap_agent.quota import quota_remaining, record_request

    # 配额预算：请求前检查剩余，超限熔断（每次分页请求前都会检查）
    if quota_remaining() <= 0:
        raise RuntimeError(
            "高德API配额已用尽（本月剩余 0 次）。"
            "请提高配额上限（企业认证 50000/月）或更换 Key。"
        )

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=15)
            # 配额记账：成功收到响应即计 1 次（网络层失败重试不消耗配额）
            record_request()
            data = resp.json()

            # 检查API状态
            status = data.get("status", "0")
            infocode = data.get("infocode", "")

            if status == "0":
                error_msg = data.get("info", "未知错误")
                infocode_str = str(infocode)
                logger.warning("API返回错误: status=0, info=%s, infocode=%s", error_msg, infocode)

                # 对已知的API错误直接抛出异常，让Agent显示明确提示
                ERROR_MESSAGES = {
                    "10001": f"高德API Key无效（{error_msg}）。请检查 .env 中的 AMAP_API_KEY 是否正确。",
                    "10002": f"高德API Key 权限不足（{error_msg}）。请检查Key的服务权限。",
                    "10003": f"高德API配额超限（{error_msg}）。请检查API Key余额。",
                    "10044": f"高德API配额超限（{error_msg}）。请检查API Key余额。",
                }
                if infocode_str in ERROR_MESSAGES:
                    raise RuntimeError(ERROR_MESSAGES[infocode_str])

                # 其他非认证错误，可能是搜索无结果等情况，返回空
                return {"status": "0", "info": error_msg, "pois": [], "count": "0"}

            return data

        except requests.exceptions.Timeout as e:
            last_error = e
            logger.warning("请求超时（第%d/%d次）: %s", attempt, retries, params.get("keywords", ""))
            if attempt < retries:
                time.sleep(2 ** attempt)  # 指数退避
            continue
        except requests.exceptions.ConnectionError as e:
            last_error = e
            logger.warning("连接失败（第%d/%d次）: %s", attempt, retries, params.get("keywords", ""))
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue
        except ValueError as e:
            # JSON解析失败
            last_error = e
            logger.warning("JSON解析失败（第%d/%d次）: %s", attempt, retries, e)
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

    raise RuntimeError(f"请求失败，已重试{retries}次仍无法获取数据: {last_error}")


def fetch_pois(
    api_key: str,
    keyword: str,
    region: str,
    max_pages: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    抓取高德地图指定区域、指定品类的POI数据。

    参数：
        api_key: 高德地图API Key
        keyword: 搜索关键词（如"咖啡厅"、"水果店"）
        region: 区域名称（如"北京"、"闵行区"）
        max_pages: 最大抓取页数，None表示抓取全部

    返回：
        POI原始数据字典列表

    抛出：
        RuntimeError: API配额超限时
    """
    all_pois: List[Dict[str, Any]] = []
    page = 1

    logger.info("开始抓取: keyword='%s', region='%s', max_pages=%s", keyword, region, max_pages or "全部")
    print(f"[进度] 正在抓取「{keyword}」-「{region}」的数据...")

    while True:
        params = {
            "key": api_key,
            "keywords": keyword,
            "region": region,
            "page": page,
            "offset": PAGE_SIZE,
            "extensions": "all",
        }

        logger.debug("请求URL: %s, params: %s", PLACE_TEXT_URL, {k: v for k, v in params.items() if k != "key"})
        data = _request_with_retry(PLACE_TEXT_URL, params)

        pois = data.get("pois", [])
        # count 可能为 None/缺失（高德异常时），兜底为 0
        raw_count = data.get("count") or "0"
        total_count = int(raw_count) if str(raw_count).isdigit() else 0

        if not pois:
            logger.info("第%d页无数据，抓取结束", page)
            break

        all_pois.extend(pois)
        current_total = len(all_pois)

        progress_msg = f"[进度] 正在抓取第 {page} 页 (已获取 {current_total} 条)..."
        logger.info(progress_msg)
        if page % 5 == 0:
            print(progress_msg)

        # 检查是否还有下一页
        total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE if total_count > 0 else page
        if page >= total_pages:
            logger.info("已到达最后一页（第%d页），抓取结束", page)
            break

        # 达到最大页数限制
        if max_pages is not None and page >= max_pages:
            logger.info("已达到最大页数限制（%d页），抓取结束", max_pages)
            break

        # QPS控制：每次请求后休眠
        page += 1
        time.sleep(REQUEST_INTERVAL)

    print(f"[进度] 抓取完成，共获取 {len(all_pois)} 条商家信息")
    logger.info("抓取完成: 共计 %d 条POI数据", len(all_pois))
    return all_pois


def geocode_address(
    api_key: str,
    address: str,
    city: str = "",
) -> Optional[str]:
    """
    地理编码：将文本地址转换为经纬度字符串（"经度,纬度"）。

    参数：
        api_key: 高德地图API Key
        address: 结构化地址描述（如"南京市鼓楼区政府大楼"）
        city: 可选，指定城市以收窄歧义（如"南京"）

    返回：
        经纬度字符串（如 "118.777636,32.061586"）；解析失败返回 None

    抛出：
        RuntimeError: API配额超限或Key无效时
    """
    if not address:
        logger.warning("geocode 收到空地址")
        return None

    params: Dict[str, Any] = {
        "key": api_key,
        "address": address,
    }
    if city:
        params["city"] = city

    logger.info("地理编码: address='%s', city='%s'", address, city or "未指定")
    data = _request_with_retry(GEOCODE_URL, params)

    geocodes = data.get("geocodes") or []
    if not geocodes:
        logger.warning("地理编码无结果: address='%s'", address)
        return None

    # 歧义消解：多个候选结果时优先精确级别（兴趣点/门牌号 > 道路 > 乡镇/街道 > 区县 > 城市）
    best = geocodes[0]
    best_prio = _GEOCODE_LEVEL_PRIORITY.get(best.get("level", ""), 99)
    for g in geocodes[1:]:
        prio = _GEOCODE_LEVEL_PRIORITY.get(g.get("level", ""), 99)
        if prio < best_prio:
            best, best_prio = g, prio

    if best is not geocodes[0]:
        logger.info("地理编码歧义消解: %d 个候选中优先 level='%s' 的 '%s'",
                    len(geocodes), best.get("level", ""), best.get("formatted_address", ""))

    location = best.get("location", "")
    if not location:
        logger.warning("地理编码结果缺少 location: address='%s'", address)
        return None

    logger.info("地理编码成功: '%s' -> %s (level=%s)",
                address, location, best.get("level", ""))
    return location


def split_anchors(anchor_text: str) -> List[str]:
    """
    拆分多地点锚点文本（支持中文顿号、逗号、空格、"和/与"分隔）。

    参数：
        anchor_text: 用户输入的地点锚点原文（如"南京市鼓楼区政府大楼、南京站"）

    返回：
        去空后的地点列表
    """
    import re
    parts = re.split(r"[、，,;；和与\s]+", anchor_text)
    return [p.strip() for p in parts if p.strip()]


def fetch_pois_around(
    api_key: str,
    location: str,
    keyword: str,
    radius: int = AROUND_RADIUS,
    max_pages: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    周边搜索：以经纬度为中心抓取指定半径内的POI数据。

    参数：
        api_key: 高德地图API Key
        location: 中心点经纬度字符串（"经度,纬度"）
        keyword: 搜索关键词（如"水果商超"）
        radius: 搜索半径（米），默认 AROUND_RADIUS(5000)，最大 50000
        max_pages: 最大抓取页数，None表示抓取全部

    返回：
        POI原始数据字典列表

    抛出：
        RuntimeError: API配额超限时
    """
    if not location:
        logger.warning("周边搜索收到空 location")
        return []

    all_pois: List[Dict[str, Any]] = []
    page = 1

    logger.info("开始周边搜索: keyword='%s', location='%s', radius=%d, max_pages=%s",
                keyword, location, radius, max_pages or "全部")
    print(f"[进度] 正在周边搜索「{keyword}」(半径{radius}米)...")

    while True:
        params = {
            "key": api_key,
            "location": location,
            "keywords": keyword,
            "radius": radius,
            "page": page,
            "offset": AROUND_PAGE_SIZE,
            "sortrule": "distance",
            "extensions": "all",
        }

        logger.debug("请求URL: %s, params: %s", PLACE_AROUND_URL,
                     {k: v for k, v in params.items() if k != "key"})
        data = _request_with_retry(PLACE_AROUND_URL, params)

        pois = data.get("pois", [])
        # count 可能为 None/缺失（高德异常时），兜底为 0
        raw_count = data.get("count") or "0"
        total_count = int(raw_count) if str(raw_count).isdigit() else 0

        if not pois:
            logger.info("第%d页无数据，周边搜索结束", page)
            break

        all_pois.extend(pois)
        current_total = len(all_pois)

        progress_msg = f"[进度] 周边搜索第 {page} 页 (已获取 {current_total} 条)..."
        logger.info(progress_msg)
        if page % 5 == 0:
            print(progress_msg)

        # 检查是否还有下一页
        total_pages = (total_count + AROUND_PAGE_SIZE - 1) // AROUND_PAGE_SIZE if total_count > 0 else page
        if page >= total_pages:
            logger.info("已到达最后一页（第%d页），周边搜索结束", page)
            break

        # 达到最大页数限制
        if max_pages is not None and page >= max_pages:
            logger.info("已达到最大页数限制（%d页），周边搜索结束", max_pages)
            break

        # QPS控制：每次请求后休眠
        page += 1
        time.sleep(REQUEST_INTERVAL)

    print(f"[进度] 周边搜索完成，共获取 {len(all_pois)} 条商家信息")
    logger.info("周边搜索完成: 共计 %d 条POI数据", len(all_pois))
    return all_pois


def generate_grid_anchors(
    center_location: str,
    radius: int = GRID_RADIUS,
    grid_n: int = GRID_N,
) -> List[str]:
    """
    生成 (2N+1)x(2N+1) 周边网格中心点（经纬度），用于突破单请求 200 条限制。

    高德 POI 搜索「同请求参数翻页最多 200 条」，绕开方式之一是把区域拆成多个
    网格圆心分别做 /place/around 搜索，各圆心独立拿到 200 条再合并去重。
    相邻圆心间距=radius（默认小于 AROUND_RADIUS，保证搜索圆相互覆盖不留空洞）。

    参数：
        center_location: 中心点经纬度字符串（"经度,纬度"）
        radius: 相邻圆心间距（米），默认 GRID_RADIUS
        grid_n: 网格半边长，0=仅中心点(1x1)，1=3x3(9点)，2=5x5(25点)

    返回：
        网格点经纬度字符串列表（行优先，从西到东、从北到南）

    示例：
        generate_grid_anchors("118.78,32.06", radius=2500, grid_n=1)
        -> ["118.7556,32.0825", "118.7781,32.0825", ..., "118.8006,32.0375"]
    """
    import math

    if not center_location:
        return []
    lon_s, lat_s = center_location.split(",")
    lon, lat = float(lon_s), float(lat_s)

    # 1 度纬度 ≈ 111km；经度 1 度随纬度余弦收缩（高纬度处更窄）
    dlat = radius / 111000.0
    dlon = radius / (111000.0 * max(math.cos(math.radians(lat)), 1e-6))

    points: List[str] = []
    for i in range(-grid_n, grid_n + 1):
        for j in range(-grid_n, grid_n + 1):
            points.append(f"{lon + j * dlon:.6f},{lat + i * dlat:.6f}")
    return points
