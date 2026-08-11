"""
批量任务执行器 - 串行执行多个中心点的抓取任务

对每个中心点调用 agent.run(f"{name} 周边 {keyword}")，
捕获 stdout 进度写入任务日志，逐点更新任务状态与结果，全程持久化。
"""

import contextlib
import io
import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional

from amap_agent import agent as agent_module
from workbench import state

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_task_sync(
    task_id: str,
    progress_cb: Optional[Callable[[Dict], None]] = None,
    stop_flag: Optional[object] = None,
) -> Dict:
    """
    同步执行一个批量任务（阻塞直到全部中心点完成或中断）。

    参数：
        task_id: 任务 ID
        progress_cb: 可选回调，每完成一个中心点后调用，参数为最新任务字典
        stop_flag: 可选 threading.Event；被 set 时在下一个中心点前中止

    返回：
        最终任务字典
    """
    task = state.get_task(task_id)
    if not task:
        raise ValueError(f"任务不存在: {task_id}")

    # 重跑已完成/中断的任务时，重置上一轮结果与日志，避免重复追加
    if task.get("status") in ("done", "partial"):
        state.update_task(task_id, results=[], logs=[], current_index=0)
        task = state.get_task(task_id)
        state.append_task_log(task_id, "[任务] 重新执行，上一轮结果已重置")

    state.update_task(task_id, status="running", started_at=_now(), current_index=0)
    task = state.get_task(task_id)
    state.append_task_log(task_id, f"[任务] 开始执行，共 {task['total']} 个中心点")

    centers = task.get("centers", [])
    results: List[Dict] = []
    fail_count = 0

    for idx, center in enumerate(centers, 1):
        if stop_flag is not None and stop_flag.is_set():
            state.append_task_log(task_id, "[任务] 已收到停止指令，任务中断")
            state.update_task(task_id, status="partial", finished_at=_now(), results=results)
            task = state.get_task(task_id)
            if progress_cb:
                progress_cb(task)
            return task

        name = center.get("name", "")
        keyword = center.get("keyword", "")
        state.append_task_log(task_id, f"[进度] 第 {idx}/{len(centers)} 个中心点: {name} 周边 {keyword}")
        state.update_task(task_id, current_index=idx, results=results)

        # 捕获 agent.run 的 stdout/stderr（进度提示与 WARNING 日志），写入任务日志
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                # 批量任务输入已结构化，直接构造 intent 跳过 DeepSeek 意图解析；
                # 半径取中心点配置（缺省由 run_with_intent 回退默认 5km）
                intent = {
                    "anchor": name,
                    "keyword": keyword,
                    "around": True,
                    "region": "",
                    "city": "",
                    "modifier": None,
                    "radius": center.get("radius") or 0,
                }
                result = agent_module.run_with_intent(intent, user_input=f"{name} 周边 {keyword}")
        except Exception as e:  # 单点异常不中断整体任务
            logger.exception("中心点执行异常: %s", name)
            result = {"success": False, "error": str(e)}

        captured = buf.getvalue().strip()
        if captured:
            for line in captured.splitlines():
                state.append_task_log(task_id, line)

        ok = bool(result.get("success"))
        total = 0
        file_path = ""
        if ok:
            stats = result.get("statistics") or {}
            total = stats.get("total", 0)
            file_path = result.get("file_path", "")
        else:
            fail_count += 1
            state.append_task_log(task_id, f"[警告] 中心点「{name}」执行失败: {result.get('error') or result.get('result') or result.get('ask_for_input')}")

        results.append({
            "name": name,
            "keyword": keyword,
            "radius": center.get("radius") or 0,
            "status": "done" if ok else "failed",
            "total": total,
            "file_path": file_path,
        })
        state.update_task(task_id, results=results)

        if progress_cb:
            progress_cb(state.get_task(task_id))

    final_status = "done" if fail_count == 0 else "partial"
    state.update_task(task_id, status=final_status, finished_at=_now(), results=results)
    state.append_task_log(
        task_id,
        f"[完成] 任务结束: {len(results) - fail_count}/{len(results)} 个中心点成功"
        f"（失败 {fail_count} 个）",
    )
    task = state.get_task(task_id)
    if progress_cb:
        progress_cb(task)
    return task
