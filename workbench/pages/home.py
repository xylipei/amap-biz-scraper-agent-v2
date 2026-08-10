"""
总览页 - 使用向导 + 快速搜索 + 任务概览
"""

import contextlib
import io

import streamlit as st

from amap_agent import agent as agent_module
from amap_agent import config
from workbench import state

st.title("商家数据工作台")
st.caption("三步完成批量抓取：① 配置 API Key → ② 添加中心点 → ③ 执行批量任务")

# ── 使用向导（卡片化） ──
# 统一走 state.load_api_keys()（与设置页同一数据源），避免两页读法不一致
keys = state.load_api_keys()
amap_ok = bool(keys.get("amap") and "your_" not in keys["amap"])
deepseek_ok = bool(keys.get("deepseek") and "your_" not in keys["deepseek"])
centers = state.load_centers()
tasks = state.load_tasks()

with st.container(border=True):
    st.markdown("#### 🧭 使用向导")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**① 配置 API Key**")
        if amap_ok and deepseek_ok:
            st.success("✅ 已配置")
        else:
            st.warning("⚠️ 未配置")
            if st.button("去配置", key="go_settings", use_container_width=True):
                st.switch_page("workbench/pages/settings.py")
    with c2:
        st.markdown("**② 添加中心点**")
        if centers:
            st.success(f"✅ {len(centers)} 个中心点")
        else:
            st.warning("⚠️ 暂无中心点")
            b1, b2 = st.columns(2)
            with b1:
                if st.button("去添加", key="go_centers", use_container_width=True):
                    st.switch_page("workbench/pages/centers.py")
            with b2:
                if st.button("导入示例", key="load_example", use_container_width=True):
                    added = skipped = 0
                    for addr, kw in state.EXAMPLE_CENTERS:
                        try:
                            state.add_center(addr, kw)
                            added += 1
                        except ValueError:
                            skipped += 1
                    st.toast(f"已导入示例中心点 {added} 个（跳过重复 {skipped} 个）")
                    st.rerun()
    with c3:
        st.markdown("**③ 执行任务**")
        if tasks:
            st.success(f"✅ {len(tasks)} 个任务")
        else:
            st.warning("⚠️ 暂无任务")
            if st.button("去创建", key="go_tasks", use_container_width=True):
                st.switch_page("workbench/pages/tasks.py")

# ── 配额状态（本地账本，第一性：配额即预算） ──
from amap_agent.quota import quota_limit, quota_used, quota_remaining

ql, qu, qr = quota_limit(), quota_used(), quota_remaining()
if qr <= 0:
    st.error(f"⚠️ 高德 API 配额已用尽（{ql:,} 次已全部用完），搜索将被熔断。请到「API 设置」调整上限或更换 Key。")
elif ql > 0 and qr <= ql * 0.1:
    st.warning(f"⚠️ 高德 API 配额剩余不足 10%（{qr:,}/{ql:,} 次），请注意控制搜索规模或调整上限。")
else:
    st.info(f"⚖️ 高德 API 配额：本月已用 {qu:,} / {ql:,} 次，剩余 {qr:,} 次。搜索前会预估消耗。")

    if not (amap_ok and deepseek_ok and centers and tasks):
        st.caption("💡 新手建议：按步骤依次完成；或直接点「导入示例」快速体验。")

st.divider()

# ── 快速搜索（单次） ──
with st.container(border=True):
    st.markdown("#### 🔍 快速搜索")
    st.caption("单次搜索一个中心点，适合快速验证；批量场景请使用「批量任务」页。")
    col1, col2, col3 = st.columns([4, 3, 1])
    with col1:
        address = st.text_input("搜索中心地址", placeholder="例如：南京市鼓楼区政府", key="quick_address")
    with col2:
        keyword = st.text_input("搜索关键字", placeholder="例如：水果商超", key="quick_keyword")
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
                        st.success(f"共获取 {stats['total']} 家商家，文件已保存：`{result.get('file_path')}`")
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

# ── 任务概览 ──
with st.container(border=True):
    st.markdown("#### 📊 任务概览")
    if not tasks:
        st.caption("暂无批量任务。到「中心点管理」配置中心点，再到「批量任务」一键执行。")
    else:
        done = sum(1 for t in tasks if t.get("status") == "done")
        running = sum(1 for t in tasks if t.get("status") == "running")
        partial = sum(1 for t in tasks if t.get("status") == "partial")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("任务总数", len(tasks))
        m2.metric("已完成", done)
        m3.metric("进行中", running)
        m4.metric("部分完成", partial)
        with st.expander("最近任务"):
            for t in tasks[:10]:
                st.write(f"- `{t['status']}` **{t.get('name')}** — {t.get('created_at')} — "
                         f"{t.get('total', 0)} 个中心点")
