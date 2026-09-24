"""
爬虫基类

定义所有平台爬虫的统一接口与共用逻辑:
- search(keyword, limit) -> CrawlResult
- 内置反爬会话 (AntiCrawlSession)
- 失败自动回退 Mock 数据
- 解析钩子 _parse(html/json) -> list[Product] 由子类实现
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from config import get_config
from core.anti_crawl import AntiCrawlSession
from core.models import CrawlResult, Product


logger = logging.getLogger("scraper")


class BaseScraper(ABC):
    """
    平台爬虫抽象基类

    子类需实现:
        platform: str                平台标识
        search_url(keyword) -> str  构造搜索 URL
        parse(text) -> list[Product] 解析响应为商品列表
    """

    #: 平台标识 (jd/taobao/pdd)
    platform: str = "base"
    #: 平台中文名
    platform_name: str = "未知"

    def __init__(self, session: Optional[AntiCrawlSession] = None) -> None:
        self.cfg = get_config().crawl
        self.session = session or AntiCrawlSession()

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    def search(self, keyword: str, limit: int = 30) -> CrawlResult:
        """
        搜索关键词

        Args:
            keyword: 搜索关键词
            limit: 最大返回数

        Returns:
            CrawlResult (含商品列表 / used_mock 标志 / 错误信息)
        """
        start = time.time()
        result = CrawlResult(keyword=keyword, platform=self.platform)

        try:
            # 1. 真实爬取 (带超时控制)
            products = self._do_search(keyword, limit)
            if products:
                # 2. 截断到 limit
                result.products = products[:limit]
                result.used_mock = False
                result.elapsed = round(time.time() - start, 2)
                logger.info("[%s] 真实采集成功: 关键词=%s 数量=%d 耗时=%.2fs",
                           self.platform, keyword, len(result.products), result.elapsed)
                return result

            # 3. 真实爬取返回空 -> 回退 Mock
            logger.warning("[%s] 真实采集返回空, 回退 Mock", self.platform)
            result.error = "real_crawl_empty"
        except Exception as e:
            logger.warning("[%s] 真实采集异常: %s, 回退 Mock", self.platform, e)
            result.error = f"real_crawl_exc:{type(e).__name__}:{e}"

        # 4. 回退 Mock (保留原平台标识, 便于横向对比展示)
        if self.cfg.fallback_to_mock:
            from scrapers.mock import generate_mock_for_platform
            result.products = generate_mock_for_platform(keyword, self.platform, limit)
            result.used_mock = True
            result.elapsed = round(time.time() - start, 2)
            logger.info("[%s] Mock 回退完成: 关键词=%s 数量=%d",
                       self.platform, keyword, len(result.products))
        else:
            result.elapsed = round(time.time() - start, 2)
        return result

    # ------------------------------------------------------------------
    # 子类实现
    # ------------------------------------------------------------------
    @abstractmethod
    def _do_search(self, keyword: str, limit: int) -> list[Product]:
        """
        子类实现真实爬取逻辑

        Args:
            keyword: 关键词
            limit: 上限

        Returns:
            商品列表 (空表示失败需回退)
        """
        ...

    def _sleep(self) -> None:
        """请求间随机延迟"""
        self.session.random_delay()


__all__ = ["BaseScraper"]
