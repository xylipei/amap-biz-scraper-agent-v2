"""
高德地图商家抓取 Agent — 客户工作台入口（Streamlit 多页应用）

运行方式：
    streamlit run app.py

页面：
- 总览（单次快速搜索 + 任务统计）
- API 设置（客户填写高德/DeepSeek Key）
- 中心点管理（批量配置搜索中心点）
- 批量任务（多中心点一键抓取，实时进度）
- 结果库（历史任务结果查看与下载）
- 合并分析（合并去重 + 品牌聚合导出 Excel）
"""

import streamlit as st

st.set_page_config(
    page_title="商家数据工作台",
    page_icon=":material/storefront:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 全局侧边栏品牌区（对所有页面生效）
with st.sidebar:
    st.markdown("## 🏬 商家数据工作台")
    st.caption("高德地图 × DeepSeek 智能抓取")

pages = [
    st.Page("workbench/pages/home.py", title="总览", icon=":material/home:", default=True),
    st.Page("workbench/pages/settings.py", title="API 设置", icon=":material/key:"),
    st.Page("workbench/pages/centers.py", title="中心点管理", icon=":material/location_on:"),
    st.Page("workbench/pages/tasks.py", title="批量任务", icon=":material/rocket_launch:"),
    st.Page("workbench/pages/results.py", title="结果库", icon=":material/folder_open:"),
    st.Page("workbench/pages/merge.py", title="合并分析", icon=":material/table_chart:"),
    st.Page("workbench/pages/help.py", title="使用帮助", icon=":material/help:"),
]

pg = st.navigation(pages)
pg.run()
