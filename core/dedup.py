"""
数据清洗与去重模块

功能:
1. 字段标准化 (价格/销量/标题/店铺评分)
2. 去重 (基于平台+标题归一化+价格档位)
3. 异常值过滤 (价格为 0/负/极端异常)
4. 按价格升序排序
"""

from __future__ import annotations

import re

from core.models import Product


# ---------------------------------------------------------------------------
# 字段标准化
# ---------------------------------------------------------------------------
def parse_price(raw) -> float:
    """
    解析价格字符串为 float

    支持: "¥99.50" / "99元" / "99.5" / 99.5

    Args:
        raw: 原始值

    Returns:
        价格, 解析失败返回 -1
    """
    if raw is None:
        return -1.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return -1.0
    # 去除货币符号/单位
    s = re.sub(r"[¥￥$元,，\s]", "", s)
    # 取首个数字段
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        return -1.0
    try:
        return float(m.group())
    except ValueError:
        return -1.0


def parse_sales(raw) -> int:
    """
    解析销量字符串为 int

    支持: "1.2万" / "1.2万+" / "12000" / "1.2k" / "已售1.2万件"

    Args:
        raw: 原始值

    Returns:
        销量整数, 解析失败返回 -1
    """
    if raw is None:
        return -1
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw).strip()
    if not s:
        return -1
    # 提取数字 + 单位
    m = re.search(r"(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K|亿)?", s)
    if not m:
        return -1
    num = float(m.group(1))
    unit = m.group(2)
    if unit in ("万", "w", "W"):
        num *= 10_000
    elif unit in ("千", "k", "K"):
        num *= 1_000
    elif unit == "亿":
        num *= 100_000_000
    return int(num)


def parse_rating(raw) -> float:
    """
    解析店铺评分 [0, 5]

    支持: "4.8" / "4.8分" / "96%" (按 5 分制换算)

    Returns:
        评分, 解析失败返回 -1
    """
    if raw is None:
        return -1.0
    if isinstance(raw, (int, float)):
        v = float(raw)
        if v > 5:  # 可能是百分制
            v = v / 20.0
        return round(min(v, 5.0), 2)
    s = str(raw).strip()
    if not s:
        return -1.0
    if "%" in s:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
        if m:
            return round(min(float(m.group(1)) / 20.0, 5.0), 2)
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return -1.0
    v = float(m.group())
    if v > 5:
        v = v / 20.0
    return round(min(v, 5.0), 2)


def clean_title(title: str) -> str:
    """清洗标题: 去除多余空白、emoji 占位、HTML 实体"""
    if not title:
        return ""
    s = title.strip()
    # HTML 实体
    s = re.sub(r"&[a-zA-Z]+;", " ", s)
    # 连续空白
    s = re.sub(r"\s+", " ", s)
    return s


# ---------------------------------------------------------------------------
# 主清洗函数
# ---------------------------------------------------------------------------
def clean_products(products: list[Product]) -> tuple[list[Product], dict]:
    """
    清洗、去重、排序商品列表

    流程:
    1. 字段标准化 (price/sales/shop_rating/title)
    2. 异常过滤 (price<=0 / 标题为空)
    3. 去重 (平台+标题归一化+价格档位)
    4. 按价格升序排序 (无效价格排末尾)

    Args:
        products: 原始商品列表

    Returns:
        (清洗后商品列表, 统计信息 dict)
    """
    stats = {
        "input": len(products),
        "invalid_price": 0,
        "empty_title": 0,
        "duplicates": 0,
        "output": 0,
    }

    # 1. 标准化
    cleaned: list[Product] = []
    for p in products:
        p.title = clean_title(p.title)
        p.price = parse_price(p.price)
        p.sales = parse_sales(p.sales)
        p.shop_rating = parse_rating(p.shop_rating)
        p.shop = (p.shop or "").strip()

        # 2. 异常过滤
        if not p.title:
            stats["empty_title"] += 1
            continue
        if p.price <= 0:
            stats["invalid_price"] += 1
            # 不直接丢弃, 但排在末尾
        cleaned.append(p)

    # 3. 去重 (保留首次出现, 已按平台/标题归一化/价格档位)
    seen: set = set()
    deduped: list[Product] = []
    for p in cleaned:
        if p.dedup_key in seen:
            stats["duplicates"] += 1
            continue
        seen.add(p.dedup_key)
        deduped.append(p)

    # 4. 排序: 有效价格升序, 无效价格 (-1) 排末尾
    deduped.sort(key=lambda x: (x.price < 0, x.price if x.price > 0 else float("inf")))

    stats["output"] = len(deduped)
    return deduped, stats


__all__ = [
    "clean_products",
    "clean_title",
    "parse_price",
    "parse_rating",
    "parse_sales",
]
