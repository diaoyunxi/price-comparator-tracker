"""
Mock 数据生成器

用途:
1. 真实爬虫失败时的回退, 保证演示始终可用
2. Web 初始化示例数据生成
3. 单元测试

生成策略:
- 标题: 关键词 + 品牌/型号/规格组合 (基于真实常见词库)
- 价格: 基准价格 * (0.5 ~ 2.0) 随机
- 销量: 对数分布 (少数爆款 + 多数普通)
- 店铺: 真实风格店铺名
- 店铺评分: 4.5 ~ 4.9 居多 (符合实际分布)
"""

from __future__ import annotations
from core.models import CrawlResult

import hashlib
import random
from typing import List

from core.models import Product


# ---------------------------------------------------------------------------
# 词库
# ---------------------------------------------------------------------------
BRANDS = ["小米", "华为", "荣耀", "OPPO", "vivo", "苹果", "三星", "一加", "realme",
          "魅族", "联想", "戴尔", "惠普", "华硕", "宏碁", "索尼", "JBL", "Bose",
          "漫步者", "Anker", "倍思", "绿联", "小米米家", "海尔", "美的", "格力"]

SUFFIXES = ["旗舰版", "青春版", "Pro", "Max", "Plus", "Ultra", "标准版", "增强版",
            "2024款", "二代", "三代", "X", "S", "T", "限量版", "定制版"]

SPECS = ["64G", "128G", "256G", "512G", "1T", "8+128", "12+256", "16+512",
         "蓝牙5.3", "Type-C", "USB3.0", "快充66W", "120Hz"]

SHOP_PREFIXES = ["官方旗舰店", "自营旗舰店", "专卖店", "专营店", "数码专营店",
                 "旗舰店", "官方店", "授权店"]
SHOP_BRANDS = ["京东", "天猫", "拼多多", "极有家", "苏宁", "国美"]

# 平台 -> 链接模板
URL_TEMPLATES = {
    "jd": "https://item.m.jd.com/product/{sku}.html",
    "taobao": "https://item.taobao.com/item.htm?id={sku}",
    "pdd": "https://mobile.yangkeduo.com/goods.html?goods_id={sku}",
}


def _hash_sku(keyword: str, idx: int, platform: str) -> str:
    """根据关键词+索引+平台生成稳定 SKU ID"""
    s = f"{platform}|{keyword}|{idx}"
    h = hashlib.md5(s.encode("utf-8")).hexdigest()
    return str(int(h[:12], 16) % 10_000_000_000)


def _gen_title(keyword: str) -> str:
    """生成标题: 关键词 + 品牌 + 规格 + 后缀"""
    brand = random.choice(BRANDS)
    spec = random.choice(SPECS)
    suffix = random.choice(SUFFIXES)
    return f"{brand} {keyword} {spec} {suffix}"


def _gen_price(base: float) -> float:
    """基准价 * (0.5 ~ 2.0) + 微抖动"""
    factor = random.uniform(0.5, 2.0)
    noise = random.uniform(-5, 5)
    price = base * factor + noise
    return round(max(price, 9.9), 2)


def _gen_sales() -> int:
    """对数分布销量: 5% 爆款 (1w+), 30% 中等 (1k-1w), 65% 普通 (<1k)"""
    r = random.random()
    if r < 0.05:
        return random.randint(10_000, 50_000)
    elif r < 0.35:
        return random.randint(1_000, 10_000)
    else:
        return random.randint(10, 1_000)


def _gen_shop() -> str:
    """生成店铺名"""
    brand = random.choice(BRANDS)
    shop_type = random.choice(SHOP_PREFIXES)
    return f"{brand}{shop_type}"


def _gen_rating() -> float:
    """店铺评分: 偏正态分布, 集中在 4.6-4.9"""
    r = random.gauss(4.7, 0.18)
    return round(max(4.0, min(r, 5.0)), 2)


def _base_price_for_keyword(keyword: str) -> float:
    """根据关键词长度估算基准价格"""
    return max(50.0, len(keyword) * 35.0 + 80.0)


class MockScraper:
    """
    Mock 数据生成器 (接口与 BaseScraper.search 兼容)

    不继承 BaseScraper, 避免循环回退。
    """

    platform = "mock"
    platform_name = "模拟数据"

    def search(self, keyword: str, limit: int = 30) -> "CrawlResult":
        """
        生成 Mock 商品

        Args:
            keyword: 搜索关键词 (用于生成标题和稳定 SKU)
            limit: 数量

        Returns:
            CrawlResult
        """
        base = _base_price_for_keyword(keyword)
        products: List[Product] = []
        for i in range(limit):
            title = _gen_title(keyword)
            sku = _hash_sku(keyword, i, "mock")
            products.append(Product(
                platform="mock",
                title=title,
                price=_gen_price(base),
                sales=_gen_sales(),
                shop=_gen_shop(),
                shop_rating=_gen_rating(),
                url=f"https://example.com/mock/{sku}",
                image_url="",
                sku_id=sku,
            ))
        return CrawlResult(keyword=keyword, platform="mock",
                          products=products, used_mock=True, elapsed=0.0)


def generate_mock_for_platform(keyword: str, platform: str, limit: int = 30) -> List[Product]:
    """
    为指定平台生成 Mock 商品 (用于真实爬虫回退)

    Args:
        keyword: 搜索关键词
        platform: jd/taobao/pdd
        limit: 数量

    Returns:
        Product 列表 (platform 字段为指定平台)
    """
    base = _base_price_for_keyword(keyword)
    url_tpl = URL_TEMPLATES.get(platform, "https://example.com/{sku}")
    products: List[Product] = []
    for i in range(limit):
        title = _gen_title(keyword)
        sku = _hash_sku(keyword, i, platform)
        products.append(Product(
            platform=platform,
            title=title,
            price=_gen_price(base),
            sales=_gen_sales(),
            shop=_gen_shop(),
            shop_rating=_gen_rating(),
            url=url_tpl.format(sku=sku),
            image_url="",
            sku_id=sku,
        ))
    return products


def generate_sample_dataset(keyword: str = "蓝牙耳机") -> List[Product]:
    """
    生成一份固定的示例数据集 (用于 Web 初始化展示)

    与 generate_mock_for_platform 不同, 这里使用固定种子保证内容稳定

    Args:
        keyword: 默认 "蓝牙耳机"

    Returns:
        90 条示例商品 (3 平台各 30 条)
    """
    # 使用局部 Random 实例，避免修改全局 random 状态导致多线程干扰
    local_rng = random.Random(hashlib.md5(keyword.encode("utf-8")).hexdigest()[:8])
    result: List[Product] = []
    for platform in ("jd", "taobao", "pdd"):
        result.extend(_generate_mock_for_platform_with_rng(keyword, platform, 30, local_rng))
    return result


def _generate_mock_for_platform_with_rng(keyword: str, platform: str, limit: int, rng: random.Random) -> List[Product]:
    """使用指定 Random 实例为平台生成 Mock 商品 (供 generate_sample_dataset 内部使用)"""
    base = _base_price_for_keyword(keyword)
    url_tpl = URL_TEMPLATES.get(platform, "https://example.com/{sku}")
    products: List[Product] = []
    for i in range(limit):
        title = _gen_title_with_rng(keyword, rng)
        sku = _hash_sku(keyword, i, platform)
        products.append(Product(
            platform=platform,
            title=title,
            price=_gen_price_with_rng(base, rng),
            sales=_gen_sales_with_rng(rng),
            shop=_gen_shop_with_rng(rng),
            shop_rating=_gen_rating_with_rng(rng),
            url=url_tpl.format(sku=sku),
            image_url="",
            sku_id=sku,
        ))
    return products


def _gen_title_with_rng(keyword: str, rng: random.Random) -> str:
    brand = rng.choice(BRANDS)
    spec = rng.choice(SPECS)
    suffix = rng.choice(SUFFIXES)
    return f"{brand} {keyword} {spec} {suffix}"


def _gen_price_with_rng(base: float, rng: random.Random) -> float:
    factor = rng.uniform(0.5, 2.0)
    noise = rng.uniform(-5, 5)
    price = base * factor + noise
    return round(max(price, 9.9), 2)


def _gen_sales_with_rng(rng: random.Random) -> int:
    r = rng.random()
    if r < 0.05:
        return rng.randint(10_000, 50_000)
    elif r < 0.35:
        return rng.randint(1_000, 10_000)
    else:
        return rng.randint(10, 1_000)


def _gen_shop_with_rng(rng: random.Random) -> str:
    brand = rng.choice(BRANDS)
    shop_type = rng.choice(SHOP_PREFIXES)
    return f"{brand}{shop_type}"


def _gen_rating_with_rng(rng: random.Random) -> float:
    r = rng.gauss(4.7, 0.18)
    return round(max(4.0, min(r, 5.0)), 2)


__all__ = [
    "MockScraper",
    "generate_mock_for_platform",
    "generate_sample_dataset",
]
