"""
交付中心页 - 结果库 + 合并分析（整合为一页，双 Tab）

Tab1 结果库：历史任务结果查看、逐行下载、批量勾选 ZIP、汇总 Excel
Tab2 合并分析：跨任务勾选结果文件合并去重、品牌聚合、导出品牌分组明细 Excel

注意：本页由原 results.py 与 merge.py 合并而来，两页逻辑以函数封装，
各 Tab 内不使用 st.stop()（会中断整页脚本，影响另一 Tab 渲染），改用 early return。
"""

import io
import os
import re
import zipfile

import pandas as pd
import streamlit as st

from amap_agent.merger import run_merge
from workbench import state

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

st.title(":package: 交付中心")
st.caption("结果库：查看与下载历史抓取结果；合并分析：合并去重、按品牌聚合导出交付 Excel。")


# ────────────────────── 公共工具 ──────────────────────
def _read_frame(fp):
    """读取结果文件（按扩展名 xlsx/csv），返回 DataFrame。"""
    if fp.lower().endswith(".xlsx"):
        return pd.read_excel(fp)
    return pd.read_csv(fp, encoding="utf-8-sig")


def _frame_to_excel_bytes(frame) -> bytes:
    """DataFrame 转为 Excel 文件字节。"""
    buf = io.BytesIO()
    frame.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def _safe_filename(name: str) -> str:
    """清洗文件名中的非法字符（Windows 不允许 \\/:*?"<>|）。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "结果"


# ────────────────────── Tab1 结果库 ──────────────────────
def _render_results():
    """结果库：查看历史任务的每个中心点结果，逐行/批量/汇总下载（Excel）。"""
    tasks = state.load_tasks()
    if not tasks:
        st.info("暂无任务记录。")
        return

    task_opts = {
        f"{t.get('created_at')} | {t.get('name')}（{t.get('status')}）[{t.get('id')}]": t.get("id")
        for t in tasks
    }
    sel_id = st.selectbox("选择任务", list(task_opts.keys()), key="result_task_select")
    task = state.get_task(task_opts[sel_id])

    results = task.get("results", [])
    if not results:
        st.info("该任务尚无执行结果。")
        return

    st.markdown(f"**任务**: {task.get('name')} — 共 {len(results)} 个中心点")
    df = pd.DataFrame(results)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 成功且有文件的结果
    done_items = [
        (i, r) for i, r in enumerate(results)
        if r.get("status") == "done" and r.get("file_path") and os.path.exists(r.get("file_path", ""))
    ]

    # ── 选择下载：表格勾选 + 批量 ZIP + 单行下载 ──
    if done_items:
        st.divider()
        with st.container(border=True):
            st.markdown("#### 📥 选择下载（Excel）")

            # 预先读取每个结果转 Excel 字节（单行按钮与批量打包共用）
            excel_bytes = {}
            for i, r in done_items:
                try:
                    excel_bytes[i] = _frame_to_excel_bytes(_read_frame(r["file_path"]))
                except Exception as e:
                    st.warning(f"读取 {os.path.basename(r.get('file_path', ''))} 失败: {e}")

            # 表格行：勾选 + 信息列（勾选状态由 data_editor 自管理）
            version = st.session_state.get("sel_version", 0)
            sel_all = st.session_state.get("sel_all_default", True)
            rows = []
            for i, r in done_items:
                if i not in excel_bytes:
                    continue
                rows.append({
                    "勾选": sel_all,
                    "中心点": r.get("name", ""),
                    "品类": r.get("keyword", ""),
                    "结果数": r.get("total", 0),
                    "结果文件": os.path.basename(r.get("file_path", "")),
                    "_idx": i,
                })

            if rows:
                c_all, c_none = st.columns(2)
                with c_all:
                    if st.button("☑ 全选"):
                        # 递增版本号换 data_editor key,新 key 首次渲染按 default 全勾选
                        st.session_state["sel_version"] = version + 1
                        st.session_state["sel_all_default"] = True
                        st.rerun()
                with c_none:
                    if st.button("☐ 取消全选"):
                        st.session_state["sel_version"] = version + 1
                        st.session_state["sel_all_default"] = False
                        st.rerun()

                edited = st.data_editor(
                    pd.DataFrame(rows),
                    column_config={
                        "勾选": st.column_config.CheckboxColumn("勾选", default=sel_all),
                        "结果文件": st.column_config.TextColumn("结果文件"),
                        "_idx": None,  # 内部索引列隐藏
                    },
                    disabled=["中心点", "品类", "结果数", "结果文件", "_idx"],
                    hide_index=True,
                    key=f"result_editor_v{version}",
                    use_container_width=True,
                )

                by_idx = {i: (r, excel_bytes[i]) for i, r in done_items if i in excel_bytes}
                selected = [by_idx[int(row["_idx"])] for _, row in edited.iterrows() if row["勾选"]]
                st.divider()
                if selected:
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for r, data in selected:
                            zf.writestr(
                                f"{_safe_filename(r.get('name', ''))}_{_safe_filename(r.get('keyword', ''))}.xlsx",
                                data,
                            )
                    st.download_button(
                        f"📥 批量下载选中结果（{len(selected)} 个）(ZIP)",
                        data=zip_buf.getvalue(),
                        file_name=f"selected_results_{task.get('id')}.zip",
                        mime="application/zip",
                        type="primary",
                    )
                else:
                    st.info("未勾选任何结果（点「☑ 全选」可全部勾选）。")

                # 单行下载（表格不支持按钮列，用下拉选择 + 下载按钮）
                dl_labels = {
                    f"{r.get('name')} · {r.get('keyword')}（{r.get('total', 0)} 条）": (r, excel_bytes[i])
                    for i, r in done_items if i in excel_bytes
                }
                if dl_labels:
                    chosen = st.selectbox("单行下载", list(dl_labels.keys()), key="dl_select")
                    r, data = dl_labels[chosen]
                    st.download_button(
                        "⬇ 下载所选",
                        data=data,
                        file_name=f"{_safe_filename(r.get('name', ''))}_{_safe_filename(r.get('keyword', ''))}.xlsx",
                        mime=XLSX_MIME,
                        key="dl_single",
                    )

    # ── 汇总下载：合并全部成功结果为一个 Excel ──
    files = [r.get("file_path") for r in results if r.get("file_path") and os.path.exists(r.get("file_path", ""))]
    if files:
        st.divider()
        with st.container(border=True):
            st.markdown("#### 📄 汇总下载")
            frames = []
            for fp in files:
                try:
                    frames.append(_read_frame(fp))
                except Exception as e:
                    st.warning(f"读取 {os.path.basename(fp)} 失败: {e}")
            if frames:
                merged = pd.concat(frames, ignore_index=True)
                st.download_button(
                    "📥 下载全部结果 (Excel, 未去重)",
                    data=_frame_to_excel_bytes(merged),
                    file_name=f"all_results_{task.get('id')}.xlsx",
                    mime=XLSX_MIME,
                )
        st.markdown("> 提示：需要**合并去重 + 品牌聚合**时，请切换到「合并分析」Tab 一键处理。")
    else:
        st.info("当前任务没有可读取的结果文件（可能均未成功或文件已被移动）。")


# ────────────────────── Tab2 合并分析 ──────────────────────
def _render_merge():
    """合并分析：从结果库勾选结果文件（可跨任务）合并去重、品牌聚合、导出交付 Excel。"""
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
                return
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
            return

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
                            mime=XLSX_MIME,
                        )

    st.divider()
    st.markdown(
        "**处理规则**：按（门店名称, 地址）联合去重 → 品牌名取门店名称括号前文本 → "
        "「同名门店数量」为合并后全局统计并按门店数降序 → 第1列品牌序号、第2列品牌名（合并单元格）、"
        "第3列门店数（合并单元格）、其后门店明细。"
    )


# ────────────────────── 页面主体 ──────────────────────
tab_results, tab_merge = st.tabs(["📁 结果库", "🔗 合并分析"])

with tab_results:
    _render_results()

with tab_merge:
    _render_merge()
