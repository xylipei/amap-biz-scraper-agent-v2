"""
配置模块 - 从环境变量读取API密钥及常量定义

严格遵守 5.1 安全底线：
- API Key 必须通过 os.getenv() 读取，代码中严禁明文密钥
"""

import os
import logging

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 强制 urllib3/requests 使用 IPv4：
# 本机 DNS 对 restapi.amap.com 优先返回 IPv6 地址，而 IPv6 路由不可达，
# 导致每次请求先等待 IPv6 连接超时（15s）再回退 IPv4，单请求耗时 ~30s。
# 关闭 IPv6 后请求恢复到亚秒级。curl 无此问题因其自带 Happy Eyeballs 快速回退。
import urllib3.util.connection as _urllib3_connection
_urllib3_connection.HAS_IPV6 = False

# 禁用系统/注册表代理：本机存在代理软件（DNS 解析到 fake-ip 段 198.18.x.x），
# requests 会误读 Windows 注册表系统代理导致 ProxyError('Unable to connect to proxy')。
# 统一 NO_PROXY=* 让 requests 对所有主机直连（curl 实测 fake-ip 直连可达）。
# 默认启用；若客户环境必须走企业代理，可在 .env 设置 AMAP_AGENT_NO_PROXY=0 关闭。
if os.getenv("AMAP_AGENT_NO_PROXY", "1") != "0":
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

# 加载 .env 文件（基于项目根目录显式定位，避免 Streamlit 工作目录变化时
# load_dotenv() 从 os.getcwd() 向上找不到 .env，导致 Key 读不到）
# 注意：本文件位于 amap_agent/ 下，dirname 两次即为项目根目录（与 workbench/state.py 的 ENV_FILE 推导一致）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BASE_DIR, ".env"))

# --- API 密钥 ---
AMAP_API_KEY: str = os.getenv("AMAP_API_KEY", "")
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")


def set_api_keys(amap_key: str = None, deepseek_key: str = None) -> None:
    """
    运行时更新 API Key（工作台设置页调用，立即对后续请求生效）。

    参数：
        amap_key: 高德 API Key；None 表示不修改
        deepseek_key: DeepSeek API Key；None 表示不修改
    """
    global AMAP_API_KEY, DEEPSEEK_API_KEY
    if amap_key is not None:
        AMAP_API_KEY = amap_key.strip()
    if deepseek_key is not None:
        DEEPSEEK_API_KEY = deepseek_key.strip()
    logger.info("API Key 已更新: amap=%s, deepseek=%s",
                "已设置" if AMAP_API_KEY else "未设置",
                "已设置" if DEEPSEEK_API_KEY else "未设置")


def validate_config() -> None:
    """验证必要配置是否存在，缺失则抛出 RuntimeError"""
    if not AMAP_API_KEY:
        raise RuntimeError(
            "缺少高德地图 API Key。请在 .env 文件中设置 AMAP_API_KEY，"
            "或通过环境变量 AMAP_API_KEY 传入。"
        )
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "缺少 DeepSeek API Key。请在 .env 文件中设置 DEEPSEEK_API_KEY，"
            "或通过环境变量 DEEPSEEK_API_KEY 传入。"
        )
    logger.info("配置验证通过：API Key 已就绪")


# --- 高德API 常量 ---
AMAP_BASE_URL: str = "https://restapi.amap.com/v3"
PLACE_TEXT_URL: str = f"{AMAP_BASE_URL}/place/text"
PLACE_POLYGON_URL: str = f"{AMAP_BASE_URL}/place/polygon"
PLACE_AROUND_URL: str = f"{AMAP_BASE_URL}/place/around"  # 周边搜索（按点+半径）
GEOCODE_URL: str = f"{AMAP_BASE_URL}/geocode/geo"          # 地理编码（文本地址转经纬度）

# --- 请求控制 ---
REQUEST_INTERVAL: float = 0.2  # 每次请求间隔 200ms，满足 QPS 限制
MAX_RETRIES: int = 3           # 网络超时重试次数
PAGE_SIZE: int = 20            # 高德API每页返回条数

# --- 周边搜索 ---
AROUND_RADIUS: int = 5000      # 周边搜索默认半径（米），默认 5km；可被意图/中心点动态覆盖，高德上限 50000
AROUND_PAGE_SIZE: int = 25     # 周边搜索每页条数（高德上限 25）

# --- 自动网格铺点（突破单请求 200 条限制，配合 generate_grid_anchors 使用）---
GRID_RADIUS: int = 2500        # 网格圆心间距默认值（米）；实际执行时由搜索半径推导（radius//2，默认 5000→2500）
GRID_N: int = 1                # 网格半边长：0=仅中心点(1x1)，1=3x3(9点)，2=5x5(25点)

# --- 配额预算（本地账本记账；高德不提供剩余配额查询）---
QUOTA_LIMIT: int = 5000                  # 本月配额上限（个人认证默认 5000 次/月；企业 50000、商业授权 500000 可在设置中调整）
QUOTA_COST_PER_10K: float = 30.0         # 超量单价（元/万次，官方 30 元/万次）
QUOTA_FILE: str = os.path.join(_BASE_DIR, "workbench_data", "quota_ledger.json")  # 配额账本

# --- 高德API 错误码 ---
ERR_QUOTA_EXCEEDED: tuple = ("10003", "10044")  # 配额超限
