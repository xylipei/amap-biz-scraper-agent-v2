# AGENTS.md — 高德地图商家抓取 Agent

基于 DeepSeek 大模型意图解析 + 高德地图 Web API 的商家抓取工具:自然语言输入 → 自动解析区域/品类/修饰词/半径 → 批量抓取 POI → 导出 CSV/Excel。Python 3.8+,无测试套件(验证脚本按 `_test_*.py` 约定)。需求与工程底线以 PRD.md 为准(防跑偏:禁止逻辑降级、禁止硬编码密钥)。

## Commands

```bash
pip install -r requirements.txt   # 安装依赖(requests/openpyxl/python-dotenv/openai/streamlit/pandas)
# 配置:复制 .env.example 为 .env,填入 AMAP_API_KEY / DEEPSEEK_API_KEY
streamlit run app.py              # Streamlit 客户工作台,浏览器打开 http://localhost:8501
python main.py 北京海淀区 星巴克     # CLI 单次搜索
python main.py "南京站 周边 3公里 咖啡"  # CLI 周边搜索(半径可动态指定,如 5公里/3km/500米)
python main.py                    # CLI 交互模式(单次输入后退出,q/quit 提前退出)
python merge_brands.py            # 合并 output/ 下所有商家结果:去重+品牌聚合+品牌分组 Excel
python -m py_compile <files>      # 语法检查(项目无 lint/测试命令)
venv\Scripts\python.exe -m unittest <模块名>  # 运行 _test_*.py 验证脚本(如 _test_radius_behavior)
```

无 pytest/测试目录;测试脚本按 .gitignore 约定命名 `_test_*.py`(会被 git 忽略,不会被误提交)。

## Architecture

```
app.py                     Streamlit 客户工作台入口(多页导航:总览/API设置/中心点管理/批量任务/交付中心/帮助)
main.py                    CLI 入口:setup_logging() + 全局异常兜底,不抛堆栈
merge_brands.py            合并 CLI:扫描结果文件 → merger.run_merge
amap_agent/
  agent.py                 Agent 编排 + 意图解析(run() 主流程:解析→校验→分片计划→抓取→清洗→导出→汇报;
                           意图解析规则优先+DeepSeek 兜底;run_with_intent() 供批量任务跳过 LLM 直接执行)
  fetcher.py               高德抓取:fetch_pois(/place/text)、fetch_pois_around(/place/around)、
                           geocode_address(geocode/geo)、split_anchors 多锚点拆分、generate_grid_anchors 网格铺点;
                           分页+3次重试+200ms QPS+配额错误码(10003/10044)终止
  aggregator.py            清洗统一字段、按品牌基础名统计同名门店(括号前)
  exporter.py              CSV(utf-8-sig)/Excel 导出 + 搜索历史 search_history.csv;公式注入防护
  merger.py                跨文件合并去重(门店名称+地址联合键)+ 品牌聚合 + 品牌分组 Excel(合并单元格)
  quota.py                 配额预算:本地账本记账(workbench_data/quota_ledger.json,按月)+ 搜索前预估 + 熔断
  districts.py             城市→区县内置表(15 城市;区县拆分突破单请求 200 条上限)
  config.py                环境变量读 Key + URL/常量 + 强制关闭 IPv6 + NO_PROXY 直连 + set_api_keys 热更新
workbench/                 Streamlit 工作台逻辑层
  state.py                 中心点/任务/API Key 持久化(workbench_data/*.json,原子写+损坏备份)
  task_runner.py           批量任务执行器:逐中心点构造 intent(anchor/radius)→ run_with_intent,捕获 stdout 写任务日志
  pages/                   总览(home)/API设置(settings)/中心点管理(centers)/批量任务(tasks)/交付中心(delivery)/帮助(help)
```

执行流水线(分片计划驱动,估算与执行共用同一份 plan):
- **周边模式(单通道,严格半径圈内)**:`build_fetch_plan` 只生成 around 锚点单元或 grid 网格单元 → 逐单元 geocode + `/place/around` → 按 poi id 去重 → `aggregate_and_clean` → `export_to_table`。
- **非周边模式**:text 行政区搜索(区县级)或城市级区县拆分(B 方案)。
- 前置:`estimate_plan_requests` 配额预估 → `quota_remaining()` 熔断检查。

## Conventions

- **密钥**:只从环境变量读(`os.getenv`)/工作台设置页写 `.env`,任何代码不得出现明文 API Key(PRD 5.1)。
- **中文**:docstring/注释/控制台提示全中文;进度提示用 `[进度]`/`[Agent]` 前缀;错误提示 CLI 用 `[ERROR]`(main.py),Agent 内部用 `[错误]`(agent.py)。
- **导出**:CSV 必须 `utf-8-sig`;文件名 `{区域}_{品类}_{YYYYMMDD}.xlsx` 存于 `output/`;控制台须提示绝对路径。
- **字段底线**:高德收录年份固定 `"N/A"`(高德不提供,禁止伪造)。
- **周边半径**:默认 `AROUND_RADIUS=5000`(5km),**动态设置**——自然语言意图(规则+LLM 提取 `radius` 字段,支持 公里/千米/km/米,clamp 500~50000)与工作台中心点 `radius` 字段(缺省用默认);**单通道严格半径圈内数据,不得叠加行政区 text 通道**(避免混入远离中心点的店铺)。
- **配额**:本地账本记账(高德无配额查询接口),请求前检查剩余、剩余 0 熔断;`quota_ledger.json` 已被 gitignore。
- **日志**:`logging.getLogger(__name__)` 每模块一个 logger;`main.py` 写入 `logs/amap_agent_*.log`。
- **输入路由**:`/` 分隔区域与品类;"周边/附近/周围/一带"触发周边模式;"X公里/千米/km/米"触发动态半径。
- **配置**:无依赖注入,模块顶层直接 import config 常量;改动配置后需重启进程;`set_api_keys` 运行时热更新。
- **工作台数据**:`workbench_data/`(centers.json/tasks.json/quota_ledger.json)与 `output/`、`logs/` 均已被 gitignore,不入库。

## Notes

- 本机网络坑位(config.py 内有注释):DNS 对 restapi.amap.com 返回不可达 IPv6 → 强制 IPv4;注册表代理 fake-ip → NO_PROXY=* 直连;DeepSeek 需 httpx `trust_env=False`。
- 验证脚本:根目录 `_test_radius_behavior.py`(unittest)覆盖半径解析/归一化/单通道计划/页面语法,被 gitignore。
