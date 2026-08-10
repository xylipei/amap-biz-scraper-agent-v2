"""
团购信息解析模块 - 团购检测已停用（避免 /place/detail ID 查询消耗 API 配额）

背景（2026-08）：原实现会对每个 POI 调用高德 /place/detail（ID 查询），
单次搜索数千条 POI 即消耗数千次配额（实测一次搜索 4860 次直接打满日额度）。
团购字段对业务非关键，故停用网络检测，统一返回 "fetch_failed"，
表格中显示"需人工核验(附链接)"，由用户人工确认。

保留 parse_groupbuy_info 签名以兼容调用方（agent.py），内部不再发起任何网络请求。
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _build_detail_url(poi_id: str, detail_url: str = "") -> str:
    """
    构造商户详情页 URL。

    高德 /place/around 接口返回的 POI 不包含 detail_url 字段，
    但详情页 URL 有固定格式 https://ditu.amap.com/detail/{poi_id}，
    可据此构造，保证团购字段降级时有链接可供人工核验。
    """
    if detail_url:
        return detail_url
    if poi_id:
        return f"https://ditu.amap.com/detail/{poi_id}"
    return ""


def parse_groupbuy_info(
    api_key: str,
    poi_id: str,
    detail_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    解析门店的团购信息（已停用网络检测）。

    团购检测不再调用高德 /place/detail 与 H5 详情页（避免 API 配额消耗），
    统一返回 {"groupbuy": "fetch_failed", "url": detail_url}，
    由导出层以"需人工核验(附链接)"展示。

    参数：
        api_key: 高德API Key（保留签名兼容，不再使用）
        poi_id: POI唯一ID（保留签名兼容，不再使用）
        detail_url: 商户高德详情页URL（可选）

    返回：
        {"groupbuy": "fetch_failed", "url": detail_url}
    """
    return {
        "groupbuy": "fetch_failed",
        "url": _build_detail_url(poi_id, detail_url),
    }
