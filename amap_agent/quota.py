"""
配额预算模块 - 本地账本记账高德 API 请求消耗

高德不提供剩余配额查询接口，采用本地账本记账：
- 每次 API 请求（经 fetcher._request_with_retry）消耗 +1
- 按月记录（"2026-08"），支持自定义月上限（个人 5000 / 企业 50000 / 商业 500000）
- 任务前可估算预计请求数并展示成本 / 月占比（第一性：配额即预算）
- 执行中支持熔断：剩余为 0 时立即终止

账本文件：workbench_data/quota_ledger.json（已被 gitignore，不入库）
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict

from amap_agent.config import QUOTA_LIMIT, QUOTA_COST_PER_10K, QUOTA_FILE

logger = logging.getLogger(__name__)


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _load_ledger() -> Dict[str, Dict]:
    """读取配额账本 {month: {"limit": int, "used": int}}，损坏时重建。"""
    if not os.path.exists(QUOTA_FILE):
        return {}
    try:
        with open(QUOTA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("配额账本读取失败，将重建: %s", e)
        return {}


def _save_ledger(ledger: Dict[str, Dict]) -> None:
    """保存账本（原子写：先写临时文件再替换）。"""
    os.makedirs(os.path.dirname(QUOTA_FILE), exist_ok=True)
    tmp = QUOTA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1)
    os.replace(tmp, QUOTA_FILE)


def _month_entry() -> Dict:
    ledger = _load_ledger()
    month = _current_month()
    entry = ledger.setdefault(month, {"limit": QUOTA_LIMIT, "used": 0})
    entry.setdefault("limit", QUOTA_LIMIT)
    entry.setdefault("used", 0)
    return entry


def quota_used() -> int:
    """本月已消耗的请求次数。"""
    return int(_month_entry().get("used", 0))


def quota_remaining() -> int:
    """本月剩余可用请求次数（上限 - 已用，不小于 0）。"""
    entry = _month_entry()
    limit = int(entry.get("limit", QUOTA_LIMIT))
    used = int(entry.get("used", 0))
    return max(limit - used, 0)


def quota_limit() -> int:
    """本月配额上限。"""
    return int(_month_entry().get("limit", QUOTA_LIMIT))


def set_monthly_limit(limit: int) -> None:
    """设置本月配额上限（如企业认证 50000）。limit<=0 视为不设限（仅记账不熔断）。"""
    entry = _month_entry()
    entry["limit"] = int(limit)
    ledger = _load_ledger()
    ledger[_current_month()] = entry
    _save_ledger(ledger)
    logger.info("本月配额上限已设为 %d", limit)


def record_request(n: int = 1) -> int:
    """
    记录 n 次请求消耗，返回本月累计已用数。

    说明：仅记录成功发出并收到响应的请求（网络层重试失败不消耗配额）。
    """
    entry = _month_entry()
    entry["used"] = int(entry.get("used", 0)) + int(n)
    ledger = _load_ledger()
    ledger[_current_month()] = entry
    _save_ledger(ledger)
    logger.debug("配额记账: +%d，本月已用 %d", n, entry["used"])
    return int(entry["used"])


def estimate_cost(n_requests: int) -> float:
    """按官方单价预估超量成本（元）：30 元/万次。"""
    return round(n_requests / 10000.0 * QUOTA_COST_PER_10K, 2)


def format_quota_summary(estimate: int) -> str:
    """生成配额预估摘要文案：预计 N 次请求 / 约 ¥M / 占本月 X% / 剩余 Y 次。"""
    limit = quota_limit()
    remaining = quota_remaining()
    pct = (estimate / limit * 100) if limit > 0 else 0.0
    return (
        f"预计消耗约 {estimate} 次请求（约 ¥{estimate_cost(estimate)}，占本月配额 {pct:.0f}%），"
        f"剩余 {remaining} 次"
    )
