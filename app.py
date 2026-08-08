"""
高德地图商家抓取 Agent — Streamlit 前端界面

运行方式：
    streamlit run app.py
"""

import contextlib
import io
import os
import sys
from datetime import datetime

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
st.caption("输入搜索中心地址 + 关键字，一键抓取周边商家数据并导出表格")

# ── 输入区（双框：搜索中心地址 + 关键字）──
col1, col2, col3 = st.columns([4, 3, 1])
with col1:
    address_input = st.text_input(
        "搜索中心地址",
        placeholder="例如：南京市鼓楼区政府大楼",
        label_visibility="collapsed",
        key="address_input",
    )
with col2:
    keyword_input = st.text_input(
        "搜索关键字",
        placeholder="例如：水果商超",
        label_visibility="collapsed",
        key="keyword_input",
    )
with col3:
    search_clicked = st.button(
        ":mag: 开始搜索", type="primary", use_container_width=True
    )

# 快捷示例
with st.expander(":bulb: 输入示例"):
    st.markdown("""
    | 搜索中心地址 | 搜索关键字 | 行为 |
    | :--- | :--- | :--- |
    | `南京市鼓楼区政府大楼` | `水果商超` | 以该地点为圆心，周边 3000 米内搜索水果商超 |
    | `南京站`、`新街口`（多个用顿号分隔） | `咖啡厅` | 多中心周边搜索，自动去重合并 |
    | `杭州市西湖区` | `火锅` | 以区域为圆心搜索周边 |
    """)

# ── 执行与结果区 ──
if search_clicked:
    address = (address_input or "").strip()
    keyword = (keyword_input or "").strip()

    if not address or not keyword:
        st.warning("请同时填写「搜索中心地址」和「搜索关键字」")
    else:
        # 组装为周边搜索输入，交由 Agent 解析执行
        user_input = f"{address} 周边 {keyword}"
        with st.spinner(f"正在以「{address}」为中心搜索「{keyword}」，请稍候..."):
            # 捕获 agent.run() 内部的所有 print 输出
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = agent_run(user_input)
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
                c2.metric(":star: 有评分商家", stats.get("rating_count", 0))
                c3.metric(":chart_with_downwards_trend: 无评分商家", total - stats.get("rating_count", 0))

                # 读取生成的 CSV 并展示
                file_path = result.get("file_path", "")
                if file_path and os.path.exists(file_path):
                    try:
                        df = pd.read_csv(file_path, encoding="utf-8-sig")
                        # 列名中文化
                        col_rename = {
                            "name": "门店名称",
                            "same_name_count": "同名门店数量",
                            "collect_year": "高德收录年份",
                            "pname": "省份",
                            "cityname": "城市",
                            "adname": "区县",
                            "address": "地址",
                            "tel": "电话",
                            "rating": "评分",
                            "type": "POI类型",
                            "groupbuy": "是否团购",
                            "groupbuy_url": "团购链接",
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
                                df_display.to_excel(writer, index=False, sheet_name="商家数据")
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
                    "rating_count": "有评分数",
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
