"""
结果库页 - 历史任务结果查看与下载
支持：逐行下载（Excel）、批量勾选下载（ZIP）、汇总下载（Excel）。
"""

import io
import os
import re
import zipfile

import pandas as pd
import streamlit as st

from workbench import state

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    """清洗文件名中的非法字符（Windows 不允许 \\/:*?\"<>|）。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "结果"


st.title(":folder_open: 结果库")
st.caption("查看历史任务的每个中心点抓取结果，支持逐行下载、批量下载与汇总下载（Excel）。")

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

    # 成功且有文件的结果
    done_items = [
        (i, r) for i, r in enumerate(results)
        if r.get("status") == "done" and r.get("file_path") and os.path.exists(r.get("file_path", ""))
    ]

    # ── 选择下载：逐行下载 + 批量 ZIP ──
    if done_items:
        st.divider()
        with st.container(border=True):
            st.markdown("#### 📥 选择下载（Excel）")
            c_all, c_none = st.columns(2)
            with c_all:
                if st.button("☑ 全选"):
                    # checkbox key 已存在时 value 参数被忽略，必须直接写每个勾选状态
                    for i, _ in done_items:
                        st.session_state[f"sel_{i}"] = True
                    st.session_state["sel_all"] = True
                    st.rerun()
            with c_none:
                if st.button("☐ 取消全选"):
                    for i, _ in done_items:
                        st.session_state[f"sel_{i}"] = False
                    st.session_state["sel_all"] = False
                    st.rerun()

            # 预先读取每个结果转 Excel 字节（单行按钮与批量打包共用）
            excel_bytes = {}
            for i, r in done_items:
                try:
                    excel_bytes[i] = _frame_to_excel_bytes(_read_frame(r["file_path"]))
                except Exception as e:
                    st.warning(f"读取 {os.path.basename(r.get('file_path', ''))} 失败: {e}")

            default_val = st.session_state.get("sel_all", True)
            selected = []
            for i, r in done_items:
                if i not in excel_bytes:
                    continue
                # 首次渲染按默认值初始化勾选状态；之后状态完全由 widget/session_state 管理。
                # 注意：不能给 checkbox 同时传 value=（会与全选按钮写入的 session_state 冲突，
                # 报 "created with a default value but also had its value set via the Session State API"）
                if f"sel_{i}" not in st.session_state:
                    st.session_state[f"sel_{i}"] = default_val
                col_cb, col_info, col_btn = st.columns([0.5, 5, 2.5])
                with col_cb:
                    checked = st.checkbox("", key=f"sel_{i}")
                with col_info:
                    st.write(f"**{r.get('name')}** · {r.get('keyword')} · {r.get('total', 0)} 条")
                with col_btn:
                    st.download_button(
                        "⬇ 下载",
                        data=excel_bytes[i],
                        file_name=f"{_safe_filename(r.get('name', ''))}_{_safe_filename(r.get('keyword', ''))}.xlsx",
                        mime=XLSX_MIME,
                        key=f"dl_{i}",
                    )
                if checked:
                    selected.append((r, excel_bytes[i]))

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
        st.markdown("> 提示：需要**合并去重 + 品牌聚合**时，请到「合并分析」页一键处理。")
    else:
        st.info("当前任务没有可读取的结果文件（可能均未成功或文件已被移动）。")
