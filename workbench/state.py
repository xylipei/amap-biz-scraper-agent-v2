"""
工作台状态层 - 中心点/任务/设置 的持久化读写

数据目录: workbench_data/（已加入 .gitignore）
- centers.json  中心点列表
- tasks.json    批量任务列表（含进度与结果）
- .env          客户填写的 API Key（复用现有 config 读取）
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

WORKBENCH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workbench_data")
CENTERS_FILE = os.path.join(WORKBENCH_DIR, "centers.json")
TASKS_FILE = os.path.join(WORKBENCH_DIR, "tasks.json")
ENV_FILE = os.path.join(os.path.dirname(WORKBENCH_DIR), ".env")

# 示例中心点（首页「导入示例」一键体验用）
EXAMPLE_CENTERS = [
    ("南京市鼓楼区政府", "咖啡厅"),
    ("南京夫子庙", "咖啡厅"),
    ("南京新街口", "水果商超"),
]


def _ensure_dir() -> None:
    os.makedirs(WORKBENCH_DIR, exist_ok=True)


def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        # 文件损坏时备份现场（避免用户数据丢失），再返回默认值
        try:
            backup = path + ".corrupt.bak"
            with open(path, "rb") as src, open(backup, "wb") as dst:
                dst.write(src.read())
            logger.warning("读取 %s 失败(%s)，已备份至 %s，返回默认值", path, e, backup)
        except OSError as be:
            logger.warning("读取 %s 失败(%s)，且备份失败: %s", path, e, be)
        return default


def _write_json(path: str, data: Any) -> None:
    """原子写：先写临时文件再替换，避免中途崩溃导致 JSON 损坏。"""
    _ensure_dir()
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


# ── 中心点 ──

def load_centers() -> List[Dict[str, Any]]:
    """读取中心点列表：[{id, name, keyword, enabled}]"""
    centers = _read_json(CENTERS_FILE, [])
    if not isinstance(centers, list):
        return []
    return centers


def save_centers(centers: List[Dict[str, Any]]) -> None:
    _write_json(CENTERS_FILE, centers)


def add_center(name: str, keyword: str, enabled: bool = True, radius: Optional[int] = None) -> Dict[str, Any]:
    """新增中心点（名称+关键字去重校验）；radius 为周边搜索半径（米），None 表示用全局默认。
    非 None 时统一 clamp 到 [500, 50000]（与执行链路 _normalize_radius 口径一致，保证存储/展示/执行一致）。"""
    centers = load_centers()
    name = (name or "").strip()
    keyword = (keyword or "").strip()
    for c in centers:
        if c.get("name") == name and c.get("keyword") == keyword:
            raise ValueError(f"中心点已存在: {name} / {keyword}")
    if radius is not None:
        radius = max(500, min(int(radius), 50000))
    center = {
        "id": "c_" + uuid.uuid4().hex[:8],
        "name": name,
        "keyword": keyword,
        "radius": radius,
        "enabled": enabled,
    }
    centers.append(center)
    save_centers(centers)
    return center


def update_center(center_id: str, **fields) -> bool:
    """更新中心点字段（name/keyword/enabled/radius）"""
    centers = load_centers()
    for c in centers:
        if c.get("id") == center_id:
            for k in ("name", "keyword", "enabled", "radius"):
                if k in fields:
                    c[k] = fields[k]
            save_centers(centers)
            return True
    return False


def remove_center(center_id: str) -> bool:
    """删除中心点"""
    centers = load_centers()
    remaining = [c for c in centers if c.get("id") != center_id]
    if len(remaining) == len(centers):
        return False
    save_centers(remaining)
    return True


# ── 任务 ──

def load_tasks() -> List[Dict[str, Any]]:
    tasks = _read_json(TASKS_FILE, [])
    if not isinstance(tasks, list):
        return []
    return tasks


def save_tasks(tasks: List[Dict[str, Any]]) -> None:
    _write_json(TASKS_FILE, tasks)


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    for t in load_tasks():
        if t.get("id") == task_id:
            return t
    return None


def create_task(name: str, centers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """创建任务并持久化，返回任务字典"""
    task = {
        "id": "t_" + uuid.uuid4().hex[:8],
        "name": name or f"任务{datetime.now().strftime('%m%d_%H%M')}",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending",  # pending/running/done/partial/failed
        "total": len(centers),
        "current_index": 0,
        "centers": [
            {"name": c.get("name", ""), "keyword": c.get("keyword", ""), "radius": c.get("radius")}
            for c in centers
        ],
        "results": [],   # [{name, keyword, status, total, file_path}]
        "logs": [],
        "started_at": "",
        "finished_at": "",
    }
    tasks = load_tasks()
    tasks.insert(0, task)  # 最新在前
    save_tasks(tasks)
    return task


def update_task(task_id: str, **fields) -> Optional[Dict[str, Any]]:
    """更新任务字段并持久化，返回更新后的任务"""
    tasks = load_tasks()
    for t in tasks:
        if t.get("id") == task_id:
            for k, v in fields.items():
                t[k] = v
            save_tasks(tasks)
            return t
    return None


def append_task_log(task_id: str, line: str) -> None:
    """追加任务日志（保留最近 500 行）"""
    tasks = load_tasks()
    for t in tasks:
        if t.get("id") == task_id:
            t.setdefault("logs", []).append(line)
            t["logs"] = t["logs"][-500:]
            save_tasks(tasks)
            return


# ── API Key 设置 ──

def save_api_keys(amap_key: str, deepseek_key: str) -> None:
    """
    保存 API Key 到 .env 并调用 config.set_api_keys 立即生效。

    仅当输入非空时覆盖对应项；已有值保留。
    """
    from amap_agent import config

    existing = {}
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        existing[k.strip()] = v.strip()
        except OSError as e:
            logger.warning("读取 .env 失败: %s", e)

    if amap_key:
        existing["AMAP_API_KEY"] = amap_key.strip()
    if deepseek_key:
        existing["DEEPSEEK_API_KEY"] = deepseek_key.strip()

    lines = [f"{k}={v}" for k, v in existing.items()]
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    config.set_api_keys(existing.get("AMAP_API_KEY", ""), existing.get("DEEPSEEK_API_KEY", ""))
    logger.info("API Key 已保存至 %s", ENV_FILE)


def load_api_keys() -> Dict[str, str]:
    """返回当前生效的 Key（amap/deepseek，未配置为空串）"""
    from amap_agent import config

    return {
        "amap": config.AMAP_API_KEY,
        "deepseek": config.DEEPSEEK_API_KEY,
    }
