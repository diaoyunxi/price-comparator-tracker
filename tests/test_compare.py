"""
商品对比与推荐模块单元测试

覆盖:
- normalize: Min-Max 归一化 (正/反转/空列表)
- compute_recommendations: 推荐排序/字典映射正确性/空输入
- platform_stats: 平台聚合统计/有效价格计数
- cheapest_vs_most_expensive: 价差计算
- build_compare_table: 表格行生成
"""

import sys
from pathlib import Path

# 将项目根目录加入 sys.path, 便于直接运行 pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from core.compare import (
    build_compare_table,
    cheapest_vs_most_expensive,
    compute_recommendations,
    normalize,
    platform_stats,
)
from core.models import Product


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------
class TestNormalize:
    """归一化测试"""

    def test_basic(self):
        result = normalize([1.0, 2.0, 3.0, 4.0, 5.0])
        assert result[0] == 0.0
        assert result[-1] == 1.0

    def test_invert(self):
        """反转: 最小值应映射为 1.0"""
        result = normalize([1.0, 5.0], invert=True)
        assert result[0] == 1.0
        assert result[1] == 0.0

    def test_empty(self):
        assert normalize([]) == []

    def test_single_value(self):
        """单值不应除零"""
        result = normalize([42.0])
        assert len(result) == 1
        assert result[0] == 0.0


# ---------------------------------------------------------------------------
# compute_recommendations
# ---------------------------------------------------------------------------
class TestComputeRecommendations:
    """推荐计算测试"""

    def _make(self, title, price, sales=-1, rating=-1.0, platform="jd", url=""):
        return Product(platform=platform, title=title, price=price,
                       sales=sales, shop_rating=rating, url=url)

    def test_empty(self):
        assert compute_recommendations([]) == []

    def test_ranking(self):
        """价格最低的应排在前面"""
        p1 = self._make("贵", 500.0, sales=100, rating=4.0, url="http://x/1")
        p2 = self._make("便宜", 50.0, sales=100, rating=4.0, url="http://x/2")
        recs = compute_recommendations([p1, p2], top_n=2)
        assert len(recs) == 2
        assert recs[0].rank == 1
        assert recs[0].product.price == 50.0

    def test_mapping_with_invalid_price(self):
        """无效价格商品不应影响有效商品的归一化映射"""
        p1 = self._make("有效A", 100.0, sales=100, rating=4.0, url="http://x/1")
        p2 = self._make("无效", -1.0, sales=100, rating=4.0, url="http://x/2")
        p3 = self._make("有效B", 200.0, sales=100, rating=4.0, url="http://x/3")
        recs = compute_recommendations([p1, p2, p3], top_n=3)
        assert len(recs) == 3
        # 最低价商品应排第一
        assert recs[0].product.title == "有效A"

    def test_top_n_limit(self):
        products = [self._make(f"商品{i}", float(i + 1) * 10, url=f"http://x/{i}")
                    for i in range(10)]
        recs = compute_recommendations(products, top_n=3)
        assert len(recs) == 3


# ---------------------------------------------------------------------------
# platform_stats
# ---------------------------------------------------------------------------
class TestPlatformStats:
    """平台统计测试"""

    def test_basic(self):
        products = [
            Product(platform="jd", title="A", price=100.0, url="http://x/1"),
            Product(platform="jd", title="B", price=200.0, url="http://x/2"),
            Product(platform="taobao", title="C", price=50.0, url="http://x/3"),
        ]
        stats = platform_stats(products)
        stats_by_plat = {s.platform: s for s in stats}
        assert stats_by_plat["jd"].count == 2
        assert stats_by_plat["jd"].avg_price == 150.0
        assert stats_by_plat["taobao"].count == 1

    def test_count_only_valid_price(self):
        """count 应只统计有效价格商品"""
        products = [
            Product(platform="jd", title="A", price=100.0, url="http://x/1"),
            Product(platform="jd", title="B", price=-1.0, url="http://x/2"),
        ]
        stats = platform_stats(products)
        assert len(stats) == 1
        assert stats[0].count == 1  # 只统计有效价格

    def test_skip_empty_platform(self):
        """全部无效价格的平台应被跳过"""
        products = [
            Product(platform="jd", title="A", price=-1.0, url="http://x/1"),
        ]
        stats = platform_stats(products)
        assert stats == []

    def test_platform_names(self):
        products = [
            Product(platform="jd", title="A", price=100.0, url="http://x/1"),
        ]
        stats = platform_stats(products, platform_names={"jd": "京东"})
        assert stats[0].platform == "京东"


# ---------------------------------------------------------------------------
# cheapest_vs_most_expensive
# ---------------------------------------------------------------------------
class TestCheapestVsMostExpensive:
    """价差测试"""

    def test_basic(self):
        products = [
            Product(platform="jd", title="A", price=100.0, url="http://x/1"),
            Product(platform="jd", title="B", price=300.0, url="http://x/2"),
        ]
        info = cheapest_vs_most_expensive(products)
        assert info["cheapest"].price == 100.0
        assert info["most_expensive"].price == 300.0
        assert info["price_gap"] == 200.0

    def test_empty(self):
        info = cheapest_vs_most_expensive([])
        assert info["cheapest"] is None
        assert info["most_expensive"] is None

    def test_all_invalid(self):
        products = [Product(platform="jd", title="A", price=-1.0, url="http://x/1")]
        info = cheapest_vs_most_expensive(products)
        assert info["cheapest"] is None


# ---------------------------------------------------------------------------
# build_compare_table
# ---------------------------------------------------------------------------
class TestBuildCompareTable:
    """表格生成测试"""

    def test_basic(self):
        products = [
            Product(platform="jd", title="A", price=100.0, url="http://x/1"),
        ]
        rows = build_compare_table(products)
        assert len(rows) == 1
        assert rows[0]["platform"] == "jd"
        assert rows[0]["title"] == "A"
        assert rows[0]["price"] == 100.0

    def test_empty(self):
        assert build_compare_table([]) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
