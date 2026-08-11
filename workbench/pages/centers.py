"""
中心点管理页 - 批量配置搜索中心点
"""

import pandas as pd
import streamlit as st

from amap_agent import config
from workbench import state

st.title("中心点管理")
st.caption("维护批量搜索的中心点列表：每个中心点 = 一个搜索圆心地址 + 目标品类 + 搜索半径(米)。")

centers = state.load_centers()

# ── 新增与批量导入 ──
with st.container(border=True):
    st.markdown("#### ➕ 添加中心点")
    tab_add, tab_import = st.tabs(["单个添加", "批量导入"])

    with tab_add:
        with st.form("add_center_form"):
            col1, col2, col3 = st.columns([3, 2, 2])
            name = col1.text_input("中心地址", placeholder="例如：南京市鼓楼区政府大楼")
            keyword = col2.text_input("搜索品类", placeholder="例如：水果商超")
            radius = col3.number_input(
                "搜索半径(米)",
                min_value=500,
                max_value=50000,
                value=int(config.AROUND_RADIUS),
                step=500,
                help="周边搜索半径，默认 5000 米（5km），高德上限 50000 米。仅搜索该半径圈内的店铺。",
            )
            if st.form_submit_button("添加", type="primary"):
                try:
                    state.add_center(name, keyword, radius=int(radius))
                    st.success(f"已添加: {name} / {keyword} / {int(radius)}米")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    with tab_import:
        st.markdown("每行一个中心点，格式：`中心地址,品类`（逗号或空格分隔，重复项自动跳过）；可附第三列搜索半径(米)，如 `南京站,咖啡厅,3000`（缺省用默认 5km）")
        template_csv = "中心地址,搜索品类,搜索半径(米)\n南京市鼓楼区政府,咖啡厅,5000\n南京夫子庙,咖啡厅,5000\n南京新街口,水果商超,5000\n"
        st.download_button(
            "📄 下载导入模板 (CSV)",
            data=template_csv.encode("utf-8-sig"),
            file_name="centers_template.csv",
            mime="text/csv",
        )
        bulk_text = st.text_area(
            "批量导入内容",
            height=140,
            placeholder="南京市鼓楼区政府大楼,水果商超\n南京站 咖啡厅\n新街口,火锅,3000",
        )
        if st.button("导入并追加", type="primary"):
            added = skipped = 0
            for line in bulk_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.replace("，", ",").split(",")]
                if len(parts) == 1:
                    parts = line.split()
                if len(parts) < 2:
                    skipped += 1
                    continue
                addr = parts[0]
                radius = None
                # 第三列为可选半径(米)：纯数字才解析（<500 会由 _normalize_radius clamp 到下限），
                # 避免数字被拼进品类词
                if len(parts) >= 3 and parts[-1].isdigit():
                    radius = int(parts[-1])
                    kw = " ".join(parts[1:-1])
                else:
                    kw = " ".join(parts[1:])
                try:
                    state.add_center(addr, kw, radius=radius)
                    added += 1
                except ValueError:
                    skipped += 1
            st.success(f"导入完成：新增 {added} 个，跳过 {skipped} 个（重复或格式错误）")
            st.rerun()

# ── 现有列表 ──
with st.container(border=True):
    st.markdown(f"#### 📋 现有中心点（{len(centers)} 个）")
    if not centers:
        st.caption("暂无中心点，请在上方添加或批量导入。")
    else:
        df = pd.DataFrame([
            {"序号": i + 1, "中心地址": c.get("name", ""), "搜索品类": c.get("keyword", ""),
             "搜索半径(米)": c.get("radius") or config.AROUND_RADIUS,
             "启用": "是" if c.get("enabled", True) else "否"}
            for i, c in enumerate(centers)
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Excel 导出（用于客户交付）
        import io as _io
        _buf = _io.BytesIO()
        df.to_excel(_buf, index=False, engine="openpyxl")
        st.download_button(
            "📤 下载中心点列表 (Excel)",
            data=_buf.getvalue(),
            file_name="centers.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # ── 删除（二次确认，防误删） ──
        st.divider()
        del_opts = {f"{c.get('name')} / {c.get('keyword')}": c.get("id") for c in centers}
        to_del = st.selectbox("选择要删除的中心点", list(del_opts.keys()))
        if st.button("🗑 删除所选", type="secondary"):
            st.session_state["pending_del"] = del_opts[to_del]
            st.rerun()
        if st.session_state.get("pending_del"):
            pending = st.session_state["pending_del"]
            del_name = next((k for k, v in del_opts.items() if v == pending), "")
            st.warning(f"⚠️ 确认删除「{del_name}」？此操作不可恢复。")
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("确认删除", type="primary", use_container_width=True):
                    state.remove_center(pending)
                    st.session_state.pop("pending_del", None)
                    st.success("已删除")
                    st.rerun()
            with cc2:
                if st.button("取消", use_container_width=True):
                    st.session_state.pop("pending_del", None)
                    st.rerun()
