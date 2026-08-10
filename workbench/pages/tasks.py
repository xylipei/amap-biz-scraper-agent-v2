"""
批量任务页 - 多中心点一键抓取，实时进度展示
"""

import pandas as pd
import streamlit as st

from amap_agent import config
from workbench import state
from workbench import task_runner

st.title(":rocket_launch: 批量任务")
st.caption("选择中心点创建批量任务，一键执行全部中心点的周边搜索。")

centers = state.load_centers()
enabled_centers = [c for c in centers if c.get("enabled", True)]

# ── 创建任务 ──
st.subheader("创建新任务")
if not enabled_centers:
    st.warning("没有可用的中心点，请先到「中心点管理」页添加。")
else:
    with st.form("create_task_form"):
        task_name = st.text_input("任务名称", placeholder="例如：南京水果商超 30 中心点")
        options = {
            f"{c.get('name')} / {c.get('keyword')}": c
            for c in enabled_centers
        }
        default_all = list(options.keys())
        selected = st.multiselect("选择中心点", list(options.keys()), default=default_all)
        if st.form_submit_button("创建任务"):
            if not selected:
                st.warning("请至少选择一个中心点")
            else:
                picked = [options[k] for k in selected]
                task = state.create_task(task_name or "未命名任务", picked)
                st.success(f"任务已创建: {task['id']}（{len(picked)} 个中心点）")
                st.rerun()

st.divider()

# ── 任务列表与执行 ──
st.subheader("任务列表")
tasks = state.load_tasks()
if not tasks:
    st.info("暂无任务。")
else:
    task_opts = {f"{t.get('created_at')} | {t.get('name')}（{t.get('status')}）[{t.get('id')}]": t.get("id") for t in tasks}
    sel_task_id = st.selectbox("选择任务", list(task_opts.keys()), key="task_select")
    task = state.get_task(task_opts[sel_task_id])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("状态", task.get("status"))
    c2.metric("中心点", task.get("total", 0))
    c3.metric("已完成", task.get("current_index", 0))
    c4.metric("成功", sum(1 for r in task.get("results", []) if r.get("status") == "done"))

    run_clicked = st.button("▶️ 开始执行", type="primary", disabled=task.get("status") == "running")
    if run_clicked:
        try:
            config.validate_config()
        except RuntimeError as e:
            st.error(f"配置缺失：{e}。请先到「API 设置」页填写 Key。")
        else:
            st.session_state["running_task_id"] = task["id"]

    if st.session_state.get("running_task_id") == task.get("id"):
        status_box = st.status(f"正在执行任务…", expanded=True)
        progress_bar = st.progress(0.0)
        log_box = st.empty()

        def on_progress(t):
            total = max(t.get("total", 1), 1)
            progress_bar.progress(min(t.get("current_index", 0) / total, 1.0))
            status_box.update(
                label=f"第 {t.get('current_index', 0)}/{t.get('total', 0)} 个中心点",
                state="running",
            )
            logs = t.get("logs", [])
            log_box.code("\n".join(logs[-20:]), language="text")

        try:
            final = task_runner.run_task_sync(task["id"], progress_cb=on_progress)
        except Exception as e:
            status_box.update(label=f"任务执行异常: {e}", state="error")
            st.error(f"任务执行异常: {e}")
            final = state.get_task(task["id"])
        finally:
            st.session_state.pop("running_task_id", None)

        progress_bar.progress(1.0)
        ok = sum(1 for r in final.get("results", []) if r.get("status") == "done")
        fail = len(final.get("results", [])) - ok
        status_box.update(
            label=f"执行完成：成功 {ok} / 失败 {fail}",
            state="complete" if fail == 0 else "error",
        )
        st.success(f"任务完成！成功 {ok} 个中心点，失败 {fail} 个。可在「结果库」查看明细。")
        # 用运行后的最新任务数据渲染日志与结果表（避免展示执行前快照）
        task = final

    with st.expander("任务日志"):
        st.code("\n".join(task.get("logs", [])), language="text")

    results = task.get("results", [])
    if results:
        st.markdown("**执行结果**")
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
