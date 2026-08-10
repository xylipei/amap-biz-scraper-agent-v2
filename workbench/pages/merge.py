"""
合并分析页 - 合并去重 + 品牌聚合导出 Excel
"""

import os

import streamlit as st

from amap_agent.merger import run_merge
from workbench import state

st.title("合并分析")
st.caption("从结果库勾选要合并的结果文件（可跨任务多选），合并去重、按品牌聚合，导出品牌分组明细 Excel。")

with st.container(border=True):
    source_mode = st.radio(
        "数据来源",
        ["结果库（任务结果）", "指定 CSV 目录"],
        horizontal=True,
        index=0,
    )

    input_paths: list = []
    source_desc = ""

    if source_mode == "结果库（任务结果）":
        # 汇总结果库中所有任务的成功结果文件，供勾选合并
        all_results = []
        for t in state.load_tasks():
            for r in t.get("results", []):
                fp = r.get("file_path", "")
                if r.get("status") == "done" and fp and os.path.exists(fp):
                    all_results.append({
                        "task": t.get("name", ""),
                        "center": r.get("name", ""),
                        "keyword": r.get("keyword", ""),
                        "total": r.get("total", 0),
                        "file_path": fp,
                    })
        if not all_results:
            st.info("结果库中暂无成功的结果文件。请先在「批量任务」页执行任务。")
            st.stop()
        options = {
            f"[{r['task']}] {r['center']} / {r['keyword']}（{r['total']}家）": r["file_path"]
            for r in all_results
        }
        selected = st.multiselect(
            "选择要合并的结果（可跨任务多选）",
            list(options.keys()),
            default=list(options.keys()),
            key="merge_result_select",
        )
        input_paths = [options[k] for k in selected]
        source_desc = f"结果库中勾选的 {len(input_paths)}/{len(all_results)} 个结果文件"
    else:
        default_dir = os.path.abspath("output")
        input_dir = st.text_input("结果目录", value=default_dir)
        if os.path.isdir(input_dir):
            input_paths = [
                os.path.join(input_dir, f) for f in sorted(os.listdir(input_dir))
                if (f.lower().endswith(".csv") or f.lower().endswith(".xlsx"))
                and f != "search_history.csv"
                and not f.startswith("merged_brands")
            ]
            source_desc = f"目录「{input_dir}」下的 {len(input_paths)} 个结果文件"

    if not input_paths:
        st.warning("请至少勾选一个结果文件（或指定包含结果文件的目录）。")
        st.stop()

    st.caption(f"📦 待合并文件：{len(input_paths)} 个 — {source_desc}")

    if st.button("🚀 开始合并", type="primary"):
        with st.spinner("正在合并去重、品牌聚合、生成 Excel..."):
            result = run_merge(input_paths, output_dir="output")
        if not result.get("success"):
            st.error(result.get("error", "合并失败"))
        else:
            stats = result["stats"]
            st.success(result["message"])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("输入文件", stats["source_files"])
            c2.metric("去重前", stats["total_before_dedupe"])
            c3.metric("去重后", stats["total_after_dedupe"])
            c4.metric("品牌数", stats["brand_count"])
            fp = result.get("file_path", "")
            if fp and os.path.exists(fp):
                with open(fp, "rb") as f:
                    st.download_button(
                        "📥 下载品牌分组明细 Excel",
                    data=f.read(),
                    file_name=os.path.basename(fp),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

st.divider()
st.markdown(
    "**处理规则**：按（门店名称, 地址）联合去重 → 品牌名取门店名称括号前文本 → "
    "「同名门店数量」为合并后全局统计并按门店数降序 → 第1列品牌序号、第2列品牌名（合并单元格）、"
    "第3列门店数（合并单元格）、其后门店明细。"
)
