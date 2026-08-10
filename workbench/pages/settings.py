"""
API 设置页 - 客户填写高德/DeepSeek Key，保存后立即生效并回显
"""

import streamlit as st

from workbench import state

st.title(":key: API 设置")
st.caption("高德地图与 DeepSeek 的 API Key 保存在本机 .env 文件中，保存后立即生效，无需重启。")

current = state.load_api_keys()
amap_ok = bool(current.get("amap"))
deepseek_ok = bool(current.get("deepseek"))

# ── 配置状态回显（卡片化） ──
with st.container(border=True):
    st.markdown("#### 当前配置状态")
    c1, c2 = st.columns(2)
    with c1:
        if amap_ok:
            st.success("✅ 高德地图 Key 已配置")
        else:
            st.error("❌ 高德地图 Key 未配置")
    with c2:
        if deepseek_ok:
            st.success("✅ DeepSeek Key 已配置")
        else:
            st.error("❌ DeepSeek Key 未配置")

st.divider()

# ── 填写 / 更新（卡片化） ──
with st.container(border=True):
    with st.form("api_key_form"):
        st.markdown("#### 填写 / 更新 API Key")
        st.text_input(
            "高德地图 API Key",
            value=current.get("amap", ""),
            placeholder="请输入高德 Web 服务 Key（console.amap.com 申请）",
            type="password",
            key="amap_key_input",
            help="已配置时显示为密码点；如需更新直接覆盖后保存。",
        )
        st.text_input(
            "DeepSeek API Key",
            value=current.get("deepseek", ""),
            placeholder="请输入 DeepSeek API Key（platform.deepseek.com 申请）",
            type="password",
            key="deepseek_key_input",
            help="已配置时显示为密码点；如需更新直接覆盖后保存。",
        )
        submitted = st.form_submit_button("保存 Key", type="primary")

if submitted:
    amap_val = st.session_state.get("amap_key_input", "").strip()
    ds_val = st.session_state.get("deepseek_key_input", "").strip()
    if not amap_val and not ds_val:
        st.error("请至少填写一个 API Key（留空表示保留原有配置）")
    else:
        state.save_api_keys(amap_val, ds_val)
        # 保存后强制整页刷新，让顶部状态区读取最新配置回显
        st.session_state["api_saved"] = True
        st.rerun()

# 保存成功回显（rerun 后仍显示）
if st.session_state.pop("api_saved", False):
    st.success("✅ API Key 已保存并立即生效，上方状态已更新。")

st.divider()

# ── 配额预算（本地账本） ──
from amap_agent.quota import quota_limit, quota_used, quota_remaining, set_monthly_limit

with st.container(border=True):
    st.markdown("#### ⚖️ 配额预算")
    st.caption(
        "高德 API 按调用次数计费（超量 30 元/万次）。本地账本自动记录每次请求，"
        "配额用尽自动熔断；搜索前会预估消耗并展示。"
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("本月配额上限", f"{quota_limit():,}")
    c2.metric("已使用", f"{quota_used():,}")
    c3.metric("剩余", f"{quota_remaining():,}")
    with st.form("quota_form"):
        st.number_input(
            "月配额上限（次）",
            min_value=100,
            max_value=100_000_000,
            value=quota_limit(),
            step=1000,
            key="quota_limit_input",
            help="个人认证默认 5000/月；企业认证 50000/月；商业授权 500000/月。按您的 Key 档位填写。",
        )
        q_submit = st.form_submit_button("保存配额上限")

if q_submit:
    new_limit = int(st.session_state.get("quota_limit_input", quota_limit()))
    set_monthly_limit(new_limit)
    st.session_state["quota_saved"] = True
    st.rerun()
if st.session_state.pop("quota_saved", False):
    st.success(f"✅ 配额上限已更新为 {quota_limit():,} 次/月。")

st.divider()
st.info(
    "**说明**：\n"
    "- 密钥仅保存在本机 `.env` 文件中（已加入 .gitignore，不会提交到仓库）\n"
    "- 高德 Key 申请：https://console.amap.com/dev/key/app\n"
    "- DeepSeek Key 申请：https://platform.deepseek.com/api_keys"
)
