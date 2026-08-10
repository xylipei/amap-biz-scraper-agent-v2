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

# ── 配置状态回显（保存后经 st.rerun 刷新，保持与 .env 一致） ──
st.subheader("当前配置状态")
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

# ── 填写 / 更新 ──
with st.form("api_key_form"):
    st.subheader("填写 / 更新 API Key")
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
st.info(
    "**说明**：\n"
    "- 密钥仅保存在本机 `.env` 文件中（已加入 .gitignore，不会提交到仓库）\n"
    "- 高德 Key 申请：https://console.amap.com/dev/key/app\n"
    "- DeepSeek Key 申请：https://platform.deepseek.com/api_keys"
)
