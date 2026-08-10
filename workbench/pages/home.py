"""
总览页 - 快速单次搜索 + 任务统计
"""

import contextlib
import io

import streamlit as st

from amap_agent import agent as agent_module
from amap_agent import config
from workbench import state

st.title(":earth_asia: 高德商家抓取工作台")
st.caption("三步上手：配置 Key → 添加中心点 → 一键批量抓取。也可以直接点「导入示例」体验完整流程。")

# ── 使用向导：新手三步引导 ──
st.subheader(":compass: 使用向导")
amap_ok = bool(config.AMAP_API_KEY and "your_" not in config.AMAP_API_KEY)
deepseek_ok = bool(config.DEEPSEEK_API_KEY and "your_" not in config.DEEPSEEK_API_KEY)
centers = state.load_centers()
tasks = state.load_tasks()

w1, w2, w3 = st.columns(3)
with w1:
    step1_ok = amap_ok and deepseek_ok
    if step1_ok:
        st.success("✅ 第 1 步：API Key 已配置")
    else:
        st.warning("⚠️ 第 1 步：请先配置 API Key")
        if st.button("去「API 设置」页", key="go_settings"):
            st.switch_page("workbench/pages/settings.py")
with w2:
    if centers:
        st.success(f"✅ 第 2 步：已配置 {len(centers)} 个中心点")
    else:
        st.warning("⚠️ 第 2 步：还没有中心点")
        c_a, c_b = st.columns(2)
        with c_a:
            if st.button("去添加", key="go_centers"):
                st.switch_page("workbench/pages/centers.py")
        with c_b:
            if st.button("导入示例", key="load_example"):
                _added = _skip = 0
                for addr, kw in state.EXAMPLE_CENTERS:
                    try:
                        state.add_center(addr, kw)
                        _added += 1
                    except ValueError:
                        _skip += 1
                st.success(f"已导入示例中心点 {_added} 个（跳过重复 {_skip} 个），现在可以去「批量任务」创建任务了！")
                st.rerun()
with w3:
    if tasks:
        st.success(f"✅ 第 3 步：已有 {len(tasks)} 个任务")
    else:
        st.warning("⚠️ 第 3 步：还没有批量任务")
        if st.button("去「批量任务」页", key="go_tasks"):
            st.switch_page("workbench/pages/tasks.py")

if not (step1_ok and centers and tasks):
    st.info("💡 新手建议：依次完成第 1、2、3 步；或直接点「导入示例」快速体验完整流程。")

st.divider()

# ── 单次快速搜索 ──
st.subheader(":mag: 快速搜索（单次）")
col1, col2, col3 = st.columns([4, 3, 1])
with col1:
    address = st.text_input("搜索中心地址", placeholder="例如：南京市鼓楼区政府大楼", label_visibility="collapsed", key="quick_address")
with col2:
    keyword = st.text_input("搜索关键字", placeholder="例如：水果商超", label_visibility="collapsed", key="quick_keyword")
with col3:
    clicked = st.button("开始搜索", type="primary", use_container_width=True)

if clicked:
    address = (address or "").strip()
    keyword = (keyword or "").strip()
    if not address or not keyword:
        st.warning("请同时填写「搜索中心地址」和「搜索关键字」")
    else:
        try:
            config.validate_config()
        except RuntimeError as e:
            st.error(f"配置缺失：{e}")
        else:
            with st.spinner(f"正在以「{address}」为中心搜索「{keyword}」，请稍候..."):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    result = agent_module.run(f"{address} 周边 {keyword}")
                logs = buf.getvalue()
            if result.get("success"):
                stats = result.get("statistics") or {}
                if stats.get("total", 0) > 0:
                    st.success(f"✅ 共获取 {stats['total']} 家商家，文件已保存至：`{result.get('file_path')}`")
                else:
                    st.info(result.get("result", "未找到相关商家"))
            elif result.get("ask_for_input"):
                st.warning(f"参数不完整：{result['ask_for_input']}")
            else:
                st.error(result.get("error", "执行失败"))
            if logs.strip():
                with st.expander("执行日志"):
                    st.code(logs.strip(), language="text")

st.divider()

# ── 任务统计 ──
st.subheader(":clipboard: 任务概览")
tasks = state.load_tasks()
if not tasks:
    st.info("暂无批量任务。到「中心点管理」配置中心点，再到「批量任务」一键执行。")
else:
    done = sum(1 for t in tasks if t.get("status") == "done")
    running = sum(1 for t in tasks if t.get("status") == "running")
    partial = sum(1 for t in tasks if t.get("status") == "partial")
    c1, c2, c3 = st.columns(3)
    c1.metric("任务总数", len(tasks))
    c2.metric("已完成", done)
    c3.metric("进行中 / 部分完成", f"{running} / {partial}")
    with st.expander("最近任务"):
        for t in tasks[:10]:
            st.write(f"- `{t['status']}` **{t.get('name')}** — {t.get('created_at')} — "
                     f"{t.get('total', 0)} 个中心点")
