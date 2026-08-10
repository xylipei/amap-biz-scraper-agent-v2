"""
批量任务页 - 多中心点一键抓取，实时进度展示
"""

import threading

import pandas as pd
import streamlit as st

from amap_agent import config
from workbench import state
from workbench import task_runner

st.title("批量任务")
st.caption("选择中心点创建批量任务，一键执行全部中心点的周边搜索，实时查看进度与日志。")

centers = state.load_centers()
enabled_centers = [c for c in centers if c.get("enabled", True)]

# ── 创建任务 ──
with st.container(border=True):
    st.markdown("#### ➕ 创建新任务")
    if not enabled_centers:
        st.warning("没有可用的中心点，请先到「中心点管理」页添加。")
    else:
        with st.form("create_task_form"):
            task_name = st.text_input("任务名称", placeholder="例如：南京水果商超 30 中心点")
            options = {f"{c.get('name')} / {c.get('keyword')}": c for c in enabled_centers}
            selected = st.multiselect(
                "选择中心点",
                list(options.keys()),
                default=list(options.keys()),
                help="默认全选所有中心点，可取消不需要的。",
            )
            st.caption(f"已选 {len(selected)} / {len(options)} 个中心点")
            if st.form_submit_button("创建任务", type="primary"):
                if not selected:
                    st.warning("请至少选择一个中心点")
                else:
                    picked = [options[k] for k in selected]
                    task = state.create_task(task_name or "未命名任务", picked)
                    st.success(f"任务已创建：{task['name']}（{len(picked)} 个中心点），可在下方选择并执行。")
                    st.rerun()

st.divider()

# ── 任务列表与执行 ──
with st.container(border=True):
    st.markdown("#### 🚀 任务执行")
    tasks = state.load_tasks()
    if not tasks:
        st.caption("暂无任务，请先在上方创建。")
    else:
        task_opts = {f"{t.get('created_at')} | {t.get('name')}（{t.get('status')}）[{t.get('id')}]": t.get("id") for t in tasks}
        sel_task_id = st.selectbox("选择任务", list(task_opts.keys()), key="task_select")
        task = state.get_task(task_opts[sel_task_id])

        st.markdown(f"**{task.get('name')}**")
        c1, c2, c3, c4 = st.columns(4)
        status_map = {"done": "已完成", "running": "执行中", "partial": "部分完成", "pending": "待执行"}
        c1.metric("状态", status_map.get(task.get("status"), task.get("status")))
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
                # 后台线程执行，避免阻塞页面；切页/刷新不中断任务
                thread = threading.Thread(
                    target=task_runner.run_task_sync,
                    args=(task["id"],),
                    daemon=True,
                )
                st.session_state["task_thread"] = thread
                st.session_state["running_task_id"] = task["id"]
                thread.start()
                st.rerun()

        thread = st.session_state.get("task_thread")
        is_this_task = st.session_state.get("running_task_id") == task.get("id")

        if is_this_task and thread is not None and thread.is_alive():
            # 执行中：轮询展示最新进度
            live = state.get_task(task["id"]) or task
            total = max(live.get("total", 1), 1)
            idx = live.get("current_index", 0)
            st.progress(min(idx / total, 1.0))
            st.info(f"⏳ 正在执行：第 {idx}/{live.get('total', 0)} 个中心点…（成功 "
                    f"{sum(1 for r in live.get('results', []) if r.get('status') == 'done')} 个）")
            logs = live.get("logs", [])
            with st.expander("实时日志", expanded=False):
                st.code("\n".join(logs[-30:]), language="text")
            st.caption("任务在后台执行中，可切到其他页面；返回本页或点下方按钮刷新进度。")
            if st.button("🔄 刷新进度"):
                st.rerun()
            task = live
        elif is_this_task and thread is not None and not thread.is_alive():
            # 线程已结束：收尾展示最终结果
            final = state.get_task(task["id"]) or task
            st.session_state.pop("task_thread", None)
            st.session_state.pop("running_task_id", None)
            ok = sum(1 for r in final.get("results", []) if r.get("status") == "done")
            fail = len(final.get("results", [])) - ok
            st.success(f"任务完成！成功 {ok} 个中心点，失败 {fail} 个。可在「交付中心」查看明细。")
            task = final
        elif task.get("status") == "running" and (thread is None or not thread.is_alive()):
            # 中断遗留：页面重启后无活动线程但任务停在 running
            st.warning("⚠️ 上次执行被中断（页面刷新或关闭），任务仍标记为「执行中」。")
            if st.button("重置为待执行"):
                state.update_task(task["id"], status="pending")
                st.rerun()

        with st.expander("任务日志", expanded=False):
            st.code("\n".join(task.get("logs", [])), language="text")

        results = task.get("results", [])
        if results:
            st.markdown("**执行结果**")
            res_df = pd.DataFrame([
                {"中心点": r.get("name"), "品类": r.get("keyword"),
                 "状态": "成功" if r.get("status") == "done" else "失败",
                 "结果数": r.get("total", 0), "结果文件": r.get("file_path", "")}
                for r in results
            ])
            st.dataframe(res_df, use_container_width=True, hide_index=True)
