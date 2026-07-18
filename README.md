# 高德地图商家抓取 Agent

基于 DeepSeek 大模型 + 高德地图 API 的智能商家信息抓取工具。支持自然语言输入，自动解析区域/品类/修饰词，批量抓取商家数据并导出 CSV / Excel 表格。

## 功能亮点

- **智能意图解析** — DeepSeek 自动识别「区域」「品类」「团购」等修饰词
- **高德 POI 搜索** — 分页循环 + 重试机制 + QPS 限速，稳定抓取不遗漏
- **同名门店统计** — 自动识别品牌连锁，聚合同名门店数量
- **团购检测** — 自动抓取团购状态，反爬时优雅降级
- **双格式导出** — 每次搜索同时支持 CSV 和 Excel 下载
- **搜索历史记录** — 自动保存搜索记录，支持 Excel 导出
- **Streamlit 前端** — 零代码可视化操作界面

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
git clone git@github.com:xylipei/amap-biz-scraper-agent.git
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

浏览器打开 `http://localhost:8501`，输入搜索内容即可。

**方式二：命令行**

```bash
# 单次搜索
python main.py 北京海淀区 星巴克

# 团购搜索
python main.py 上海闵行区/水果团购

# 交互模式
python main.py
```

## 使用示例

| 输入 | Agent 行为 |
|:---|:---|
| `北京海淀区 星巴克` | 搜索海淀区星巴克，导出全部门店 |
| `上海闵行区/水果团购` | 自动修正关键词为"水果店"，仅保留有团购商家 |
| `深圳 咖啡厅` | 搜索深圳全市咖啡厅 |
| `杭州西湖区 火锅` | 搜索西湖区火锅店 |

## 项目结构

```
amap-biz-scraper-agent/
├── amap_agent/           # 核心模块
│   ├── agent.py          # Agent 编排 + DeepSeek 意图解析
│   ├── fetcher.py        # 高德 POI 抓取（分页 + 重试 + QPS）
│   ├── aggregator.py     # 数据清洗 + 同名统计 + 团购过滤
│   ├── groupbuy.py       # 团购信息检测
│   ├── exporter.py       # CSV/Excel 导出 + 搜索记录
│   └── config.py         # 配置读取 + 常量
├── app.py                # Streamlit 前端界面
├── main.py               # CLI 命令行入口
├── output/               # 生成的 CSV/Excel 文件（自动创建）
├── logs/                 # 运行日志（自动创建）
├── .env.example          # API Key 模板
└── requirements.txt      # Python 依赖
```

## 常见问题

**Q: 提示"在 XX 区域未找到相关商家"？**

A: 可能是区域名称格式问题。高德 API 要求区县级区域，Agent 会自动规范化。如果仍失败，尝试简化区域（如"西湖区"而非"浙江省杭州市西湖区"）。

**Q: 团购状态显示"需人工核验"？**

A: 高德详情页触发了反爬机制，Agent 已优雅降级。该商家仍会出现在表格中，可通过链接手动确认。

**Q: API 配额超限？**

A: 高德免费版 API 每日有调用次数限制。Agent 检测到配额超限会自动停止，请次日再试或升级 API 套餐。
