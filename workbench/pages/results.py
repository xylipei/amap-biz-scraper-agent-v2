"""
结果库页 - 历史任务结果查看与下载
"""

import os

import pandas as pd
import streamlit as st

from workbench import state

st.title(":folder_open: 结果库")
st.caption("查看历史任务的每个中心点抓取结果，支持预览与下载。")

tasks = state.load_tasks()
if not tasks:
    st.info("暂无任务记录。")
    st.stop()

task_opts = {f"{t.get('created_at')} | {t.get('name')}（{t.get('status')}）[{t.get('id')}]": t.get("id") for t in tasks}
sel_id = st.selectbox("选择任务", list(task_opts.keys()), key="result_task_select")
task = state.get_task(task_opts[sel_id])

results = task.get("results", [])
if not results:
    st.info("该任务尚无执行结果。")
else:
    st.markdown(f"**任务**: {task.get('name')} — 共 {len(results)} 个中心点")
    df = pd.DataFrame(results)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 汇总下载:合并所有成功结果为一个 CSV
    files = [r.get("file_path") for r in results if r.get("file_path") and os.path.exists(r.get("file_path", ""))]
    if files:
        st.divider()
        st.subheader("汇总下载")
        frames = []
        for fp in files:
            try:
                frames.append(pd.read_csv(fp, encoding="utf-8-sig"))
            except Exception as e:
                st.warning(f"读取 {os.path.basename(fp)} 失败: {e}")
        if frames:
            merged = pd.concat(frames, ignore_index=True)
            st.download_button(
                "📥 下载全部结果 (CSV, 未去重)",
                data=merged.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"all_results_{task.get('id')}.csv",
                mime="text/csv",
            )
        st.markdown("> 提示：需要**合并去重 + 品牌聚合**时，请到「合并分析」页一键处理。")
    else:
        st.info("当前任务没有可读取的结果文件（可能均未成功或文件已被移动）。")
