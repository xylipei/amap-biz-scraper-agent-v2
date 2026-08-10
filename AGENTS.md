# AGENTS.md — 高德地图商家抓取 Agent

基于 DeepSeek 大模型意图解析 + 高德地图 Web API 的商家抓取工具:自然语言输入 → 自动解析区域/品类/修饰词 → 批量抓取 POI → 导出 CSV/Excel。Python 3.8+,无测试套件。需求与工程底线以 PRD.md 为准(防跑偏:禁止逻辑降级、禁止硬编码密钥)。

## Commands

```bash
pip install -r requirements.txt   # 安装依赖(requests/openpyxl/python-dotenv/openai/streamlit/pandas)
# 配置:复制 .env.example 为 .env,填入 AMAP_API_KEY / DEEPSEEK_API_KEY
streamlit run app.py              # Streamlit 前端,浏览器打开 http://localhost:8501
python main.py 北京海淀区 星巴克     # CLI 单次搜索
python main.py                    # CLI 交互模式(单次输入后退出,q/quit 提前退出)
python -m py_compile <files>      # 语法检查(项目无 lint/测试命令)
```

无 pytest/测试目录;测试脚本按 .gitignore 约定命名 `_test_*.py`(会被 git 忽略,不会被误提交)。

## Architecture

```
app.py                     Streamlit 前端:组装 "{地址} 周边 {关键词}" 输入 → agent.run() → 展示表格/下载/历史
main.py                    CLI 入口:setup_logging() + 全局异常兜底,不抛堆栈
amap_agent/
  agent.py                 Agent 编排 + DeepSeek 意图解析(run() 主流程:解析→校验→抓取→清洗→团购→导出→汇报)
  fetcher.py               高德抓取:fetch_pois(/place/text)、fetch_pois_around(/place/around)、geocode_address(geocode/geo);分页+3次重试+200ms QPS+配额错误码(10003/10044)终止
  aggregator.py            清洗统一字段、按品牌基础名统计同名门店(括号前)、apply_groupbuy_filter 场景B团购过滤
  groupbuy.py              团购检测:detail API → H5 页面降级 → 全部失败返回 fetch_failed(永不崩溃)
  exporter.py              CSV(utf-8-sig)/Excel 导出 + 搜索历史 search_history.csv;公式注入防护
  config.py                环境变量读 Key + URL/常量 + 强制关闭 IPv6(本机 DNS 的 IPv6 不可达)
```

执行流水线:`fetch_pois → aggregate_and_clean → _detect_groupbuy → (场景B过滤) → export_to_table`。

## Conventions

- **密钥**:只从环境变量读(`os.getenv`),任何代码不得出现明文 API Key(PRD 5.1)。
- **异常隔离**:单个门店团购检测失败不影响整体列表与文件导出(agent.py 中已有 try/except 兜底)。
- **中文**:docstring/注释/控制台提示全中文;进度提示用 `[进度]`/`[Agent]` 前缀;错误提示 CLI 用 `[ERROR]`(main.py),Agent 内部用 `[错误]`(agent.py)。
- **导出**:CSV 必须 `utf-8-sig`;文件名 `{区域}_{品类}_{YYYYMMDD}.csv` 存于 `output/`;控制台须提示绝对路径。
- **字段底线**:高德收录年份固定 `"N/A"`(高德不提供,禁止伪造);团购失败填 `"fetch_failed"` → 表格显示"需人工核验(附链接)"。
- **日志**:`logging.getLogger(__name__)` 每模块一个 logger;`main.py` 写入 `logs/amap_agent_*.log`。
- **输入路由**:`/` 分隔区域与品类;"团购"是修饰词不是关键词("水果团购"→搜"水果店"+ groupbuy 过滤);"周边/附近/周围"触发 around 周边搜索模式。
- **配置**:无依赖注入,模块顶层直接 import config 常量;改动配置后需重启进程。

## Notes

- (留空,后续快速补充)
