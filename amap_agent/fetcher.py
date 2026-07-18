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
    REQUEST_INTERVAL,
    MAX_RETRIES,
    PAGE_SIZE,
    ERR_QUOTA_EXCEEDED,
)

logger = logging.getLogger(__name__)


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
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=15)
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
        total_count = int(data.get("count", "0"))

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
