"""
全局配置模块

集中管理采集工具的所有可调参数: 平台、反爬、数据库、Web 服务等。
支持通过 config.local.yaml 覆盖默认值 (config.local.yaml 已在 .gitignore 中忽略)。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List

try:
    import yaml  # 可选依赖, 缺失时使用默认配置
except ImportError:  # pragma: no cover
    yaml = None


# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent
DATA_DIR: Path = PROJECT_ROOT / "data"
RUNTIME_DIR: Path = DATA_DIR / "runtime"
EXPORT_DIR: Path = PROJECT_ROOT / "exports"
LOG_DIR: Path = PROJECT_ROOT / "logs"

for _p in (DATA_DIR, RUNTIME_DIR, EXPORT_DIR, LOG_DIR):
    _p.mkdir(parents=True, exist_ok=True)

DB_PATH: Path = RUNTIME_DIR / "history.sqlite3"
SAMPLE_PRODUCTS: Path = DATA_DIR / "sample_products.json"
SAMPLE_RESULT: Path = DATA_DIR / "sample_result.json"

VERSION_FILE: Path = PROJECT_ROOT / "VERSION"


def read_version() -> str:
    """读取当前版本号, 文件不存在时返回 0.0.0"""
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except FileNotFoundError:
        return "0.0.0"


# ---------------------------------------------------------------------------
# 配置数据类
# ---------------------------------------------------------------------------
@dataclass
class CrawlConfig:
    """爬虫与反爬配置"""
    # 每关键词每平台抓取条数
    limit_per_platform: int = 30
    # 请求间隔随机区间 (秒)
    request_delay_min: float = 2.0
    request_delay_max: float = 5.0
    # 失败重试次数
    max_retries: int = 3
    # 退避基数 (秒), 第 n 次重试等待 base * 2^n
    backoff_base: float = 1.5
    # 请求超时 (秒)
    request_timeout: int = 15
    # 是否启用代理池 (默认关闭, 避免无可用代理时全部失败)
    enable_proxy_pool: bool = False
    # 代理池文件路径 (每行一个 http://ip:port)
    proxy_pool_file: str = str(PROJECT_ROOT / "proxy_pool.txt")
    # 是否在 requests 失败时回退到 playwright 浏览器
    enable_playwright_fallback: bool = True
    # 是否启用 Cookie 池
    enable_cookie_pool: bool = False
    cookie_dir: str = str(PROJECT_ROOT / "cookies")
    # 请求失败时是否回退到 Mock 数据 (保证演示可用)
    fallback_to_mock: bool = True
    # 真实爬虫最大尝试时长 (秒), 超时则回退 Mock
    real_crawl_timeout: int = 60


@dataclass
class DBConfig:
    """SQLite 配置"""
    path: str = str(DB_PATH)
    # 历史保留天数, 0 表示永久保留
    retention_days: int = 0


@dataclass
class WebConfig:
    """Web 服务配置"""
    host: str = "0.0.0.0"
    port: int = 8765
    # 后台采集任务最大并发数
    max_concurrent_tasks: int = 3


@dataclass
class AppConfig:
    """应用总配置"""
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    db: DBConfig = field(default_factory=DBConfig)
    web: WebConfig = field(default_factory=WebConfig)
    # 平台标识 -> 中文名
    platforms: Dict[str, str] = field(default_factory=lambda: {
        "jd": "京东",
        "taobao": "淘宝",
        "pdd": "拼多多",
    })
    # 性价比推荐数量
    recommend_top_n: int = 5
    # GitHub 仓库 (用于自动更新检查)
    github_repo: str = "price-comparator-tracker"
    github_owner: str = ""  # 留空, 由 updater 自动检测

    def to_dict(self) -> dict:
        return asdict(self)


# 单例
_config: AppConfig = AppConfig()


def get_config() -> AppConfig:
    """获取全局配置实例"""
    return _config


def load_local_config(path: str | None = None) -> AppConfig:
    """
    从 config.local.yaml 加载用户自定义配置覆盖默认值

    Args:
        path: 配置文件路径, 默认使用项目根目录下 config.local.yaml

    Returns:
        更新后的 AppConfig 实例
    """
    global _config
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.local.yaml"
    if not cfg_path.exists() or yaml is None:
        return _config

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    # 简单平铺覆盖 (不递归, 仅顶层 + 已知子项)
    if "crawl" in raw and isinstance(raw["crawl"], dict):
        for k, v in raw["crawl"].items():
            if hasattr(_config.crawl, k):
                setattr(_config.crawl, k, v)
    if "db" in raw and isinstance(raw["db"], dict):
        for k, v in raw["db"].items():
            if hasattr(_config.db, k):
                setattr(_config.db, k, v)
    if "web" in raw and isinstance(raw["web"], dict):
        for k, v in raw["web"].items():
            if hasattr(_config.web, k):
                setattr(_config.web, k, v)
    if "recommend_top_n" in raw:
        _config.recommend_top_n = int(raw["recommend_top_n"])
    return _config


__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "RUNTIME_DIR",
    "EXPORT_DIR",
    "LOG_DIR",
    "DB_PATH",
    "SAMPLE_PRODUCTS",
    "SAMPLE_RESULT",
    "read_version",
    "AppConfig",
    "CrawlConfig",
    "DBConfig",
    "WebConfig",
    "get_config",
    "load_local_config",
]
