"""
高德地图商家抓取 Agent — Streamlit 前端界面

运行方式：
    streamlit run app.py
"""

import contextlib
import io
import os
import sys

import pandas as pd
import streamlit as st

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from amap_agent.agent import run as agent_run


st.set_page_config(
    page_title="高德地图商家抓取 Agent",
    page_icon=":earth_asia:",
    layout="wide",
)

st.title(":earth_asia: 高德地图商家抓取 Agent")
st.caption("输入区域 + 品类，一键抓取商家数据并导出表格")

# ── 输入区 ──
col1, col2 = st.columns([4, 1])
with col1:
    user_input = st.text_input(
        "搜索内容",
        placeholder="例如：北京海淀区 星巴克  或  上海闵行区/水果团购",
        label_visibility="collapsed",
        key="search_input",
    )
with col2:
    search_clicked = st.button(
        ":mag: 开始搜索", type="primary", use_container_width=True
    )

# 快捷示例
with st.expander(":bulb: 输入示例"):
    st.markdown("""
    - `北京海淀区 星巴克`
    - `上海闵行区/水果团购`
    - `深圳 咖啡厅`
    - `杭州西湖区 火锅`
    """)

# ── 执行与结果区 ──
if search_clicked and user_input.strip():
    with st.spinner(f"正在解析「{user_input}」并抓取数据，请稍候..."):
        # 捕获 agent.run() 内部的所有 print 输出
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = agent_run(user_input.strip())
        logs = buf.getvalue()

    # ── 结果渲染 ──
    if result.get("success"):
        stats = result.get("statistics") or {}
        total = stats.get("total", 0)

        if total == 0:
            st.info(result.get("result", "未找到相关商家"))
        else:
            # 统计卡片
            c1, c2, c3 = st.columns(3)
            c1.metric(":bar_chart: 商家总数", total)
            c2.metric(
                ":white_check_mark: 支持团购", stats.get("groupbuy_yes", 0)
            )
            c3.metric(
                ":warning: 需人工核验", stats.get("groupbuy_failed", 0)
            )

            # 读取生成的 CSV 并展示
            file_path = result.get("file_path", "")
            if file_path and os.path.exists(file_path):
                try:
                    df = pd.read_csv(file_path, encoding="utf-8-sig")
                    # 列名中文化
                    col_rename = {
                        "name": "门店名称",
                        "address": "地址",
                        "location": "经纬度",
                        "pname": "省份",
                        "cityname": "城市",
                        "adname": "区县",
                        "tel": "电话",
                        "type": "POI类型",
                        "same_name_count": "同名门店数量",
                        "groupbuy": "是否支持团购",
                        "groupbuy_url": "团购详情页",
                        "collect_year": "高德收录年份",
                    }
                    df_display = df.rename(
                        columns={
                            k: v
                            for k, v in col_rename.items()
                            if k in df.columns
                        }
                    )
                    st.dataframe(
                        df_display, use_container_width=True, hide_index=True
                    )

                    # 下载按钮（CSV + Excel 双按钮并排）
                    csv_name = os.path.basename(file_path)
                    xlsx_name = csv_name.replace(".csv", ".xlsx")

                    col_dl1, col_dl2 = st.columns(2)
                    with col_dl1:
                        with open(file_path, "rb") as f:
                            csv_bytes = f.read()
                        st.download_button(
                            label=":inbox_tray: 下载 CSV",
                            data=csv_bytes,
                            file_name=csv_name,
                            mime="text/csv",
                            use_container_width=True,
                        )
                    with col_dl2:
                        from io import BytesIO
                        output = BytesIO()
                        with pd.ExcelWriter(output, engine="openpyxl") as writer:
                            df.to_excel(writer, index=False, sheet_name="商家数据")
                        st.download_button(
                            label=":page_facing_up: 下载 Excel",
                            data=output.getvalue(),
                            file_name=xlsx_name,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )
                except Exception as e:
                    st.error(f"读取结果文件失败: {e}")
            else:
                st.warning("文件路径无效或文件不存在")

            # 执行结果摘要
            msg = result.get("result", "")
            if msg:
                st.success(msg)

    elif result.get("ask_for_input"):
        st.warning(
            f":warning: 参数不完整：{result['ask_for_input']}\n\n请补充后重新搜索。"
        )
    else:
        st.error(
            f":x: 执行失败：{result.get('error', '未知错误')}"
        )

    # ── 日志折叠区 ──
    if logs.strip():
        with st.expander(":clipboard: 执行日志"):
            st.code(logs.strip(), language="text")

elif search_clicked and not user_input.strip():
    st.warning("请输入搜索内容")

# ── 搜索历史区 ──
with st.expander(":scroll: 搜索历史记录", expanded=False):
    from amap_agent.exporter import get_search_history_path

    history_path = get_search_history_path()
    if os.path.exists(history_path):
        try:
            df_history = pd.read_csv(history_path, encoding="utf-8-sig")
            if not df_history.empty:
                history_col_rename = {
                    "search_time": "搜索时间",
                    "user_input": "原始输入",
                    "region": "区域",
                    "keyword": "品类",
                    "modifier": "修饰词",
                    "total": "结果数",
                    "groupbuy_yes": "团购成功",
                    "groupbuy_failed": "降级数量",
                    "file_path": "生成文件",
                }
                df_h = df_history.rename(
                    columns={k: v for k, v in history_col_rename.items() if k in df_history.columns}
                )
                st.dataframe(df_h, use_container_width=True, hide_index=True)

                # Excel 下载
                from io import BytesIO
                output = BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df_h.to_excel(writer, index=False, sheet_name="搜索记录")
                st.download_button(
                    label=":inbox_tray: 下载搜索记录 (Excel)",
                    data=output.getvalue(),
                    file_name=f"搜索记录_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                st.info("暂无搜索记录")
        except Exception as e:
            st.warning(f"读取搜索记录失败: {e}")
    else:
        st.info("暂无搜索记录，开始搜索后自动生成")
