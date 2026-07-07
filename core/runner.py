"""
采集编排器

负责:
1. 并行/串行调度多平台爬虫
2. 汇总结果并清洗去重
3. 入库历史数据库
4. 计算对比 / 推荐统计
5. 生成最终结果对象 (供 CLI / Web / Viz 共用)
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from config import get_config
from core.compare import (
    Recommendation, PlatformStats, build_compare_table,
    compute_recommendations, platform_stats, cheapest_vs_most_expensive,
)
from core.database import Database
from core.dedup import clean_products
from core.models import CrawlResult, Product
from scrapers import get_scraper


logger = logging.getLogger("runner")


@dataclass
class AggregatedResult:
    """
    采集编排最终结果

    包含完整链路产出: 原始统计 / 清洗后商品 / 平台对比 / 性价比推荐 / 价差信息
    """
    keyword: str
    platforms: List[str]
    started_at: str
    elapsed: float = 0.0
    # 各平台原始采集结果 (用于展示 used_mock/error)
    raw_results: List[dict] = field(default_factory=list)
    # 清洗后商品 (按价格升序)
    products: List[Product] = field(default_factory=list)
    # 清洗统计
    clean_stats: dict = field(default_factory=dict)
    # 平台对比统计
    platform_stats: List[PlatformStats] = field(default_factory=list)
    # 性价比推荐
    recommendations: List[Recommendation] = field(default_factory=list)
    # 价差信息
    cheapest: Optional[Product] = None
    most_expensive: Optional[Product] = None
    price_gap: float = 0.0
    price_gap_ratio: float = 0.0
    # 总条数
    total: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        # 处理 Product / Recommendation 嵌套 (asdict 已自动转换)
        return d


def run_crawl(keyword: str,
              platforms: Optional[List[str]] = None,
              limit_per_platform: Optional[int] = None,
              use_mock: bool = False,
              db: Optional[Database] = None,
              parallel: bool = True) -> AggregatedResult:
    """
    执行完整采集流程: 抓取 → 清洗 → 入库 → 对比 → 推荐

    Args:
        keyword: 搜索关键词
        platforms: 平台列表, 默认 [jd, taobao, pdd]
        limit_per_platform: 每平台条数, 默认使用配置值
        use_mock: 强制使用 Mock 数据 (跳过真实爬虫)
        db: 数据库实例, 传入 None 则不持久化
        parallel: 是否并行采集多平台

    Returns:
        AggregatedResult
    """
    cfg = get_config()
    platforms = platforms or list(cfg.platforms.keys())
    limit = limit_per_platform or cfg.crawl.limit_per_platform
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    start_ts = time.time()

    logger.info("==== 开始采集: 关键词=%s 平台=%s 数量=%d mock=%s ====",
                keyword, platforms, limit, use_mock)

    # 1. 调度爬虫
    raw_results: List[CrawlResult] = []
    if use_mock:
        # 直接走 Mock
        from scrapers.mock import generate_mock_for_platform
        for plat in platforms:
            products = generate_mock_for_platform(keyword, plat, limit)
            raw_results.append(CrawlResult(
                keyword=keyword, platform=plat,
                products=products, used_mock=True, elapsed=0.0,
            ))
    elif parallel and len(platforms) > 1:
        # 并行采集
        with ThreadPoolExecutor(max_workers=min(len(platforms), 5)) as pool:
            futures = {pool.submit(_crawl_one, kw=keyword, plat=plat, limit=limit): plat
                       for plat in platforms}
            for fut in as_completed(futures):
                plat = futures[fut]
                try:
                    raw_results.append(fut.result())
                except Exception as e:
                    logger.error("[%s] 采集失败: %s", plat, e)
                    raw_results.append(CrawlResult(
                        keyword=keyword, platform=plat, error=str(e),
                        used_mock=True,
                    ))
    else:
        # 串行
        for plat in platforms:
            raw_results.append(_crawl_one(keyword, plat, limit))

    # 2. 合并所有商品
    all_products: List[Product] = []
    for r in raw_results:
        all_products.extend(r.products)

    # 3. 清洗去重排序
    cleaned, clean_stats = clean_products(all_products)

    # 4. 入库历史
    if db is not None:
        try:
            db.save_products(keyword, cleaned)
            for r in raw_results:
                db.save_meta(keyword, r.platform, r.used_mock, r.error, r.elapsed)
        except Exception as e:
            logger.error("入库失败: %s", e)

    # 5. 平台对比统计
    plat_stats = platform_stats(cleaned, cfg.platforms)

    # 6. 性价比推荐
    recs = compute_recommendations(cleaned, top_n=cfg.recommend_top_n)

    # 7. 价差信息
    gap_info = cheapest_vs_most_expensive(cleaned)

    elapsed = round(time.time() - start_ts, 2)
    result = AggregatedResult(
        keyword=keyword,
        platforms=platforms,
        started_at=started_at,
        elapsed=elapsed,
        raw_results=[r.to_dict() for r in raw_results],
        products=cleaned,
        clean_stats=clean_stats,
        platform_stats=plat_stats,
        recommendations=recs,
        cheapest=gap_info["cheapest"],
        most_expensive=gap_info["most_expensive"],
        price_gap=gap_info["price_gap"],
        price_gap_ratio=gap_info["price_gap_ratio"],
        total=len(cleaned),
    )
    logger.info("==== 采集完成: 关键词=%s 入库=%d 推荐=%d 耗时=%.2fs ====",
                keyword, len(cleaned), len(recs), elapsed)
    return result


def _crawl_one(kw: str, plat: str, limit: int) -> CrawlResult:
    """单平台采集 (供线程池调用)"""
    try:
        scraper = get_scraper(plat)
        return scraper.search(kw, limit)
    except Exception as e:
        logger.error("[%s] 爬虫实例化失败: %s", plat, e)
        return CrawlResult(keyword=kw, platform=plat, error=str(e), used_mock=True)


__all__ = ["AggregatedResult", "run_crawl"]
