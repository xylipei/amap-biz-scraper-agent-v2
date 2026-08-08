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

# 加载 .env 文件（仅开发环境）
load_dotenv()

# --- API 密钥 ---
AMAP_API_KEY: str = os.getenv("AMAP_API_KEY", "")
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")


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
PLACE_DETAIL_URL: str = f"{AMAP_BASE_URL}/place/detail"
PLACE_AROUND_URL: str = f"{AMAP_BASE_URL}/place/around"  # 周边搜索（按点+半径）
GEOCODE_URL: str = f"{AMAP_BASE_URL}/geocode/geo"          # 地理编码（文本地址转经纬度）

# --- 请求控制 ---
REQUEST_INTERVAL: float = 0.2  # 每次请求间隔 200ms，满足 QPS 限制
MAX_RETRIES: int = 3           # 网络超时重试次数
PAGE_SIZE: int = 20            # 高德API每页返回条数

# --- 周边搜索 ---
AROUND_RADIUS: int = 3000      # 周边搜索默认半径（米），高德上限 50000
AROUND_PAGE_SIZE: int = 25     # 周边搜索每页条数（高德上限 25）

# --- 高德API 错误码 ---
ERR_QUOTA_EXCEEDED: tuple = ("10003", "10044")  # 配额超限
