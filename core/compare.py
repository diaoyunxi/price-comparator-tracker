"""
商品横向对比与性价比推荐模块

功能:
1. 计算性价比综合分 (价格归一化 + 销量归一化 + 店铺评分)
2. 标注性价比推荐 (Top N)
3. 生成横向对比表格数据 (供 CLI / Web 共用)
4. 平台级聚合统计 (均价 / 价差 / 平台价差比)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from core.models import Product


@dataclass
class Recommendation:
    """性价比推荐结果"""
    product: Product
    score: float           # 综合得分 [0, 100]
    rank: int             # 推荐名次
    reason: str           # 推荐理由 (人类可读)


@dataclass
class PlatformStats:
    """平台聚合统计"""
    platform: str
    count: int
    avg_price: float
    min_price: float
    max_price: float
    median_price: float
    avg_sales: int
    avg_rating: float


def _min_max(values: List[float]) -> tuple:
    """返回 (min, max); 空列表返回 (0, 1) 避免除零"""
    if not values:
        return 0.0, 1.0
    lo, hi = min(values), max(values)
    if hi == lo:
        return lo, hi + 1.0  # 避免除零
    return lo, hi


def normalize(values: List[float], invert: bool = False) -> List[float]:
    """
    Min-Max 归一化到 [0, 1]

    Args:
        values: 数值列表
        invert: 是否反转 (True: 越小越好, 如价格)

    Returns:
        归一化后的列表
    """
    if not values:
        return []
    lo, hi = _min_max(values)
    if invert:
        return [(hi - v) / (hi - lo) for v in values]
    return [(v - lo) / (hi - lo) for v in values]


# 推荐理由判定阈值 (可配置)
THRESHOLD_PRICE_LOW = 0.7      # 价格归一化 >= 此值视为 "价格处于低位"
THRESHOLD_PRICE_MID = 0.4      # 价格归一化 >= 此值视为 "价格适中"
THRESHOLD_SALES_HIGH = 0.6     # 销量归一化 >= 此值视为 "销量领先"
THRESHOLD_RATING_HIGH = 0.7    # 评分归一化 >= 此值视为 "店铺评分高"


def compute_recommendations(
    products: List[Product],
    top_n: int = 5,
    weights: Optional[dict] = None,
) -> List[Recommendation]:
    """
    计算性价比推荐

    综合得分 = 价格归一化(越低越好) * 0.45
            + 销量归一化(越高越好) * 0.30
            + 店铺评分归一化(越高越好) * 0.25

    Args:
        products: 商品列表 (需已清洗)
        top_n: 推荐前 N 名
        weights: 自定义权重 {price, sales, rating}

    Returns:
        推荐列表 (按得分降序)
    """
    w = weights or {"price": 0.45, "sales": 0.30, "rating": 0.25}
    sw = sum(w.values()) or 1.0
    w = {k: v / sw for k, v in w.items()}

    if not products:
        return []

    prices = [p.price for p in products if p.price > 0]
    sales = [p.sales for p in products if p.sales >= 0]
    ratings = [p.shop_rating for p in products if p.shop_rating >= 0]

    # 建立产品对象(id) -> 归一化值 的字典映射, 避免过滤后列表索引与原 products 不对应
    price_map: Dict[int, float] = {}
    if prices:
        for p, nv in zip((p for p in products if p.price > 0),
                         normalize(prices, invert=True)):
            price_map[id(p)] = nv

    sales_map: Dict[int, float] = {}
    if sales:
        for p, nv in zip((p for p in products if p.sales >= 0),
                         normalize(sales, invert=False)):
            sales_map[id(p)] = nv

    rating_map: Dict[int, float] = {}
    if ratings:
        for p, nv in zip((p for p in products if p.shop_rating >= 0),
                         normalize(ratings, invert=False)):
            rating_map[id(p)] = nv

    score_list: List[tuple] = []
    for idx, p in enumerate(products):
        # 通过字典映射获取各维度归一化值, 缺失时默认 0.0
        p_score = price_map.get(id(p), 0.0)
        s_score = sales_map.get(id(p), 0.0)
        r_score = rating_map.get(id(p), 0.0)

        total = (
            p_score * w["price"]
            + s_score * w["sales"]
            + r_score * w["rating"]
        ) * 100.0
        score_list.append((idx, total, p_score, s_score, r_score))

    score_list.sort(key=lambda x: x[1], reverse=True)

    recs: List[Recommendation] = []
    for rank, (idx, score, ps, ss, rs) in enumerate(score_list[:top_n], start=1):
        p = products[idx]
        # 生成推荐理由
        reasons = []
        if ps >= THRESHOLD_PRICE_LOW:
            reasons.append("价格处于低位")
        elif ps >= THRESHOLD_PRICE_MID:
            reasons.append("价格适中")
        if ss >= THRESHOLD_SALES_HIGH:
            reasons.append("销量领先")
        if rs >= THRESHOLD_RATING_HIGH:
            reasons.append("店铺评分高")
        if not reasons:
            reasons.append("综合表现均衡")
        recs.append(Recommendation(
            product=p, score=round(score, 2), rank=rank,
            reason=" / ".join(reasons),
        ))
    return recs


def platform_stats(products: List[Product], platform_names: Optional[dict] = None) -> List[PlatformStats]:
    """
    按平台聚合统计

    Args:
        products: 商品列表
        platform_names: 平台标识 -> 中文名 映射

    Returns:
        各平台统计列表
    """
    platform_names = platform_names or {}
    groups: Dict[str, List[Product]] = {}
    for p in products:
        groups.setdefault(p.platform, []).append(p)

    result: List[PlatformStats] = []
    for plat, items in groups.items():
        prices = [it.price for it in items if it.price > 0]
        sales = [it.sales for it in items if it.sales >= 0]
        ratings = [it.shop_rating for it in items if it.shop_rating >= 0]
        if not prices:
            continue
        sorted_p = sorted(prices)
        n = len(sorted_p)
        median = sorted_p[n // 2] if n % 2 == 1 else (sorted_p[n // 2 - 1] + sorted_p[n // 2]) / 2
        result.append(PlatformStats(
            platform=platform_names.get(plat, plat),
            count=len(prices),  # 只统计有效价格商品数量
            avg_price=round(sum(prices) / len(prices), 2),
            min_price=min(prices),
            max_price=max(prices),
            median_price=round(median, 2),
            avg_sales=int(sum(sales) / len(sales)) if sales and len(sales) > 0 else 0,
            avg_rating=round(sum(ratings) / len(ratings), 2) if ratings and len(ratings) > 0 else 0.0,
        ))
    return result


def build_compare_table(products: List[Product]) -> List[dict]:
    """
    生成横向对比表格行 (供 CLI 富文本表格与 Web 表格共用)

    Returns:
        [{'platform', 'title', 'price', 'sales', 'shop', 'shop_rating', 'url'}, ...]
    """
    rows = []
    for p in products:
        rows.append({
            "platform": p.platform,
            "title": p.title,
            "price": p.price,
            "sales": p.sales,
            "shop": p.shop,
            "shop_rating": p.shop_rating,
            "url": p.url,
            "image_url": p.image_url,
            "url_hash": p.url_hash,
        })
    return rows


def cheapest_vs_most_expensive(products: List[Product]) -> dict:
    """
    找出最便宜与最贵的商品 (用于在结果摘要中突出展示)

    Returns:
        {'cheapest': Product|None, 'most_expensive': Product|None,
         'price_gap': float, 'price_gap_ratio': float}
    """
    valid = [p for p in products if p.price > 0]
    if not valid:
        return {"cheapest": None, "most_expensive": None,
                "price_gap": 0.0, "price_gap_ratio": 0.0}
    cheapest = min(valid, key=lambda x: x.price)
    expensive = max(valid, key=lambda x: x.price)
    gap = expensive.price - cheapest.price
    ratio = round(gap / cheapest.price * 100, 2) if cheapest.price > 0 else 0.0
    return {
        "cheapest": cheapest,
        "most_expensive": expensive,
        "price_gap": round(gap, 2),
        "price_gap_ratio": ratio,
    }


__all__ = [
    "Recommendation",
    "PlatformStats",
    "normalize",
    "compute_recommendations",
    "platform_stats",
    "build_compare_table",
    "cheapest_vs_most_expensive",
]
