# 高德地图商家抓取 Agent

基于 DeepSeek 大模型 + 高德地图 API 的智能商家信息抓取工具，以 **Streamlit 客户工作台**形式交付：客户在浏览器中配置中心点、一键批量抓取、查看进度与结果、合并品牌分析并导出 Excel。

## 功能亮点

- **智能意图解析** — DeepSeek 自动识别「区域」「品类」，规则优先解析常见模式
- **周边搜索** — 支持「周边/附近/周围」多锚点搜索，**严格半径圈内单通道抓取**（不含行政区全域数据，避免混入远离中心点的店铺）；半径可动态指定（如"5公里内"），**默认 5km**，高德上限 50km
- **高德 POI 搜索** — 分页循环 + 重试机制 + QPS 限速，稳定抓取不遗漏
- **同名门店统计** — 自动识别品牌连锁，聚合同名门店数量
- **Excel 导出** — 每次搜索直接生成 Excel(.xlsx)结果文件；合并工具同时接受 CSV/Excel 输入
- **搜索历史记录** — 自动保存搜索记录，支持 Excel 导出
- **Streamlit 前端** — 零代码可视化操作界面
- **客户工作台** — 多页界面：中心点批量配置、批量任务实时进度、交付中心（结果库 + 合并分析）、界面填写 API Key 与配额预算

## 技术栈

| 层 | 技术 |
|:---|:---|
| 意图解析 | DeepSeek API (`deepseek-chat`) |
| 数据抓取 | 高德地图 Web API (`/place/text`) |
| 后端 | Python 3.8+ |
| 前端 | Streamlit |
| 导出 | pandas + openpyxl |

## 快速开始

### 1. 克隆项目

```bash
git clone git@github.com:xylipei/amap-biz-scraper-agent-v2.git
cd amap-biz-scraper-agent
```

### 2. 创建虚拟环境并安装依赖

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置 API Key

复制模板并填入真实 Key：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```
AMAP_API_KEY=你的高德APIKey
DEEPSEEK_API_KEY=你的DeepSeekAPIKey
```

> 高德 Key 申请：https://console.amap.com/dev/key/app
> DeepSeek Key 申请：https://platform.deepseek.com/api_keys

### 4. 启动

**方式一：Streamlit 前端（推荐）**

```bash
streamlit run app.py
```

浏览器打开 `http://localhost:8501`，按以下步骤使用工作台：

1. 「API 设置」页填写高德与 DeepSeek Key（保存后立即生效）
2. 「中心点管理」页添加或批量导入搜索中心点
3. 「批量任务」页创建任务并一键执行，实时查看进度与日志
4. 「交付中心」-「结果库」Tab 查看与下载各中心点结果
5. 「交付中心」-「合并分析」Tab 一键合并去重、品牌聚合，导出 Excel

**方式二：命令行**

```bash
# 单次搜索
python main.py 北京海淀区 星巴克

# 周边搜索
python main.py 南京鼓楼区政府大楼 周边 水果商超

# 交互模式
python main.py
```

## 使用示例

| 输入 | Agent 行为 |
|:---|:---|
| `北京海淀区 星巴克` | 搜索海淀区星巴克，导出全部门店 |
| `深圳 咖啡厅` | 搜索深圳全市咖啡厅 |
| `杭州西湖区 火锅` | 搜索西湖区火锅店 |
| `南京鼓楼区政府大楼 周边 水果商超` | 以该地点为圆心 3000 米搜索水果商超 |

## 项目结构

```
amap-biz-scraper-agent/
├── amap_agent/           # 核心模块
│   ├── agent.py          # Agent 编排 + DeepSeek 意图解析（规则优先，LLM 兜底）
│   ├── fetcher.py        # 高德 POI 抓取（分页 + 重试 + QPS）+ 地理编码 + 周边搜索 + 网格铺点
│   ├── aggregator.py     # 数据清洗 + 同名统计
│   ├── exporter.py       # Excel(.xlsx)导出(兼容 csv) + 搜索记录
│   ├── merger.py         # 跨文件合并去重 + 品牌聚合 + 品牌分组 Excel
│   ├── quota.py          # 配额预算（本地账本记账 + 熔断）
│   ├── districts.py      # 城市→区县内置表（区县拆分覆盖）
│   └── config.py         # 配置读取 + 常量
├── workbench/            # Streamlit 客户工作台（多页）
│   ├── state.py          # 中心点/任务/设置持久化
│   ├── task_runner.py    # 批量任务执行器（后台线程）
│   └── pages/            # 总览/API设置/中心点管理/批量任务/交付中心/帮助
├── app.py                # Streamlit 前端入口
├── main.py               # CLI 命令行入口
├── merge_brands.py       # 合并 CLI 入口
├── output/               # 生成的 Excel 结果文件（自动创建）
├── logs/                 # 运行日志（自动创建）
├── .env.example          # API Key 模板
└── requirements.txt      # Python 依赖
```

## 常见问题

**Q: 提示"在 XX 区域未找到相关商家"？**

A: 可能是区域名称格式问题。高德 API 要求区县级区域，Agent 会自动规范化。如果仍失败，尝试简化区域（如"西湖区"而非"浙江省杭州市西湖区"）。

**Q: API 配额超限？**

A: 高德免费版 API 每日有调用次数限制。Agent 检测到配额超限会自动停止，请次日再试或升级 API 套餐。
