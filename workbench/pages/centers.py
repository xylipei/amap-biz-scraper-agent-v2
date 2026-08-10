"""
中心点管理页 - 批量配置搜索中心点
"""

import pandas as pd
import streamlit as st

from workbench import state

st.title(":location_on: 中心点管理")
st.caption("维护批量搜索的中心点列表：每个中心点 = 一个搜索圆心地址 + 目标品类。")

centers = state.load_centers()

# ── 新增 ──
with st.expander("➕ 新增单个中心点", expanded=False):
    with st.form("add_center_form"):
        col1, col2 = st.columns([3, 2])
        name = col1.text_input("中心地址", placeholder="例如：南京市鼓楼区政府大楼")
        keyword = col2.text_input("搜索品类", placeholder="例如：水果商超")
        if st.form_submit_button("添加"):
            try:
                state.add_center(name, keyword)
                st.success(f"已添加: {name} / {keyword}")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

# ── 批量导入 ──
with st.expander("📥 批量导入中心点", expanded=False):
    st.markdown("每行一个中心点，格式：`中心地址,品类`（逗号或空格分隔）")
    template_csv = "中心地址,搜索品类\n南京市鼓楼区政府,咖啡厅\n南京夫子庙,咖啡厅\n南京新街口,水果商超\n"
    st.download_button(
        "📄 下载导入模板 (CSV)",
        data=template_csv.encode("utf-8-sig"),
        file_name="centers_template.csv",
        mime="text/csv",
    )
    bulk_text = st.text_area(
        "批量导入内容",
        height=150,
        placeholder="南京市鼓楼区政府大楼,水果商超\n南京站 咖啡厅\n新街口,火锅",
        help="每行一个：中心地址,品类。用逗号或空格分隔，重复项会自动跳过。",
    )
    if st.button("导入并追加"):
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
            addr, kw = parts[0], " ".join(parts[1:])
            try:
                state.add_center(addr, kw)
                added += 1
            except ValueError:
                skipped += 1
        st.success(f"导入完成：新增 {added} 个，跳过 {skipped} 个（重复或格式错误）")
        st.rerun()

# ── 现有列表 ──
st.subheader(f"现有中心点（{len(centers)} 个）")
if not centers:
    st.info("暂无中心点，请在上方新增或批量导入。")
else:
    df = pd.DataFrame([
        {
            "序号": i + 1,
            "中心地址": c.get("name", ""),
            "搜索品类": c.get("keyword", ""),
            "启用": "是" if c.get("enabled", True) else "否",
        }
        for i, c in enumerate(centers)
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.download_button(
        "📤 下载中心点列表 (CSV)",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name="centers.csv",
        mime="text/csv",
    )

    st.divider()
    st.markdown("**删除中心点**")
    del_opts = {f"{c.get('name')} / {c.get('keyword')}": c.get("id") for c in centers}
    if del_opts:
        to_del = st.selectbox("选择要删除的中心点", list(del_opts.keys()))
        if st.button("🗑 删除所选"):
            state.remove_center(del_opts[to_del])
            st.success("已删除")
            st.rerun()
