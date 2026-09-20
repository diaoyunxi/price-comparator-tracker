"""
数据模型定义

定义商品 (Product) 与采集结果 (CrawlResult) 的标准化结构。
所有平台爬虫最终都将产出 Product 列表, 保证下游清洗/对比/可视化输入一致。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional


def _norm_title(s: str) -> str:
    """标题归一化: 去除空白/特殊符号, 转小写, 用于去重"""
    if not s:
        return ""
    s = re.sub(r"[\s\-_/\\|:;,.~`'\"!?@#$%^&*()<>{}\[\]]+", "", s)
    return s.lower()


@dataclass
class Product:
    """
    单个商品标准化数据结构

    Attributes:
        platform: 平台标识 jd/taobao/pdd
        title: 商品标题
        price: 商品价格 (元), -1 表示无效
        sales: 销量 (件), 已统一为整数, -1 表示未知
        shop: 店铺名称
        shop_rating: 店铺评分 [0, 5], -1 表示未知
        url: 商品详情链接
        image_url: 主图链接 (可选)
        sku_id: 平台 SKU ID (可选, 用于趋势聚合)
    """
    platform: str
    title: str
    price: float = -1.0
    sales: int = -1
    shop: str = ""
    shop_rating: float = -1.0
    url: str = ""
    image_url: str = ""
    sku_id: str = ""

    # 运行时附加字段 (不入库)
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    # ------------------------------------------------------------------
    # 派生属性
    # ------------------------------------------------------------------
    @property
    def dedup_key(self) -> str:
        """去重 key: 平台+标题归一化+价格档位"""
        price_bucket = int(self.price) if self.price > 0 else 0
        return f"{self.platform}|{_norm_title(self.title)[:80]}|{price_bucket}"

    @property
    def url_hash(self) -> str:
        """URL SHA256 短哈希 (前16位), 用于趋势聚合稳定 ID, 碰撞概率极低"""
        return hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Product":
        return cls(
            platform=d.get("platform", ""),
            title=d.get("title", ""),
            price=float(d.get("price", -1)),
            sales=int(d.get("sales", -1)),
            shop=d.get("shop", ""),
            shop_rating=float(d.get("shop_rating", -1)),
            url=d.get("url", ""),
            image_url=d.get("image_url", ""),
            sku_id=d.get("sku_id", ""),
            fetched_at=d.get("fetched_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


@dataclass
class CrawlResult:
    """
    一次采集任务的结果

    Attributes:
        keyword: 搜索关键词
        platform: 平台
        products: 商品列表
        used_mock: 是否回退到 Mock 数据
        error: 错误信息 (成功时为空)
        elapsed: 耗时 (秒)
    """
    keyword: str
    platform: str
    products: List[Product] = field(default_factory=list)
    used_mock: bool = False
    error: str = ""
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "platform": self.platform,
            "used_mock": self.used_mock,
            "error": self.error,
            "elapsed": round(self.elapsed, 2),
            "products": [p.to_dict() for p in self.products],
        }


__all__ = ["Product", "CrawlResult", "_norm_title"]
