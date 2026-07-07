"""爬虫模块包: base / jd / taobao / pdd / mock(回退)"""

from scrapers.base import BaseScraper
from scrapers.mock import MockScraper
from scrapers.jd import JDScraper
from scrapers.taobao import TaobaoScraper
from scrapers.pdd import PddScraper


def get_scraper(platform: str):
    """根据平台标识返回对应爬虫实例"""
    plat = platform.lower()
    mapping = {
        "jd": JDScraper,
        "taobao": TaobaoScraper,
        "pdd": PddScraper,
    }
    if plat not in mapping:
        raise ValueError(f"不支持的平台: {platform}, 可选: {list(mapping.keys())}")
    return mapping[plat]()


__all__ = [
    "BaseScraper", "MockScraper",
    "JDScraper", "TaobaoScraper", "PddScraper",
    "get_scraper",
]
