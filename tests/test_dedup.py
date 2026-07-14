"""
数据清洗与去重模块单元测试

覆盖:
- parse_price: 货币符号/纯数字/空值/0 价
- parse_sales: 万/千/亿单位换算
- parse_rating: 百分制/五分制
- clean_title: 空白与 HTML 实体清理
- clean_products: 异常过滤/去重/排序
"""

import os
import sys
from pathlib import Path

# 将项目根目录加入 sys.path, 便于直接运行 pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from core.dedup import parse_price, parse_sales, parse_rating, clean_title, clean_products
from core.models import Product


# ---------------------------------------------------------------------------
# parse_price
# ---------------------------------------------------------------------------
class TestParsePrice:
    """价格解析测试"""

    def test_currency_symbols(self):
        assert parse_price("¥99.50") == 99.5
        assert parse_price("￥100") == 100.0
        assert parse_price("$50.00") == 50.0
        assert parse_price("99元") == 99.0

    def test_plain_number(self):
        assert parse_price("123.45") == 123.45
        assert parse_price(88) == 88.0
        assert parse_price(0) == 0.0

    def test_none_and_empty(self):
        assert parse_price(None) == -1.0
        assert parse_price("") == -1.0
        assert parse_price("   ") == -1.0

    def test_zero_price(self):
        """价格为 0 不应被误判为无效"""
        assert parse_price("0") == 0.0
        assert parse_price("¥0.00") == 0.0

    def test_garbage(self):
        assert parse_price("abc") == -1.0
        assert parse_price("无价") == -1.0

    def test_with_comma(self):
        assert parse_price("1,299.00") == 1299.0


# ---------------------------------------------------------------------------
# parse_sales
# ---------------------------------------------------------------------------
class TestParseSales:
    """销量解析测试"""

    def test_wan(self):
        assert parse_sales("1.2万") == 12000
        assert parse_sales("1.2万+") == 12000

    def test_qian(self):
        assert parse_sales("3千") == 3000
        assert parse_sales("2.5k") == 2500

    def test_yi(self):
        assert parse_sales("1亿") == 100_000_000

    def test_plain(self):
        assert parse_sales("500") == 500
        assert parse_sales(300) == 300

    def test_none_and_empty(self):
        assert parse_sales(None) == -1
        assert parse_sales("") == -1

    def test_with_prefix(self):
        assert parse_sales("已售1.2万件") == 12000


# ---------------------------------------------------------------------------
# parse_rating
# ---------------------------------------------------------------------------
class TestParseRating:
    """评分解析测试"""

    def test_five_scale(self):
        assert parse_rating("4.8") == 4.8
        assert parse_rating(4.5) == 4.5

    def test_percent(self):
        assert parse_rating("96%") == 4.8  # 96 / 20 = 4.8

    def test_clamp(self):
        """超过 5 分 (百分制换算后) 应被截断为 5.0"""
        # 120 视为百分制, 120/20=6.0, 截断为 5.0
        assert parse_rating("120") == 5.0

    def test_none_and_empty(self):
        assert parse_rating(None) == -1.0
        assert parse_rating("") == -1.0


# ---------------------------------------------------------------------------
# clean_title
# ---------------------------------------------------------------------------
class TestCleanTitle:
    """标题清洗测试"""

    def test_strip_whitespace(self):
        assert clean_title("  手机  ") == "手机"

    def test_html_entity(self):
        assert clean_title("手机&amp;配件") == "手机 配件"

    def test_collapse_spaces(self):
        assert clean_title("手机   配件") == "手机 配件"

    def test_empty(self):
        assert clean_title("") == ""
        assert clean_title(None) == ""


# ---------------------------------------------------------------------------
# clean_products
# ---------------------------------------------------------------------------
class TestCleanProducts:
    """商品列表清洗测试"""

    def _make(self, title="测试商品", price=99.0, platform="jd", url="http://x/1"):
        return Product(platform=platform, title=title, price=price, url=url)

    def test_empty_input(self):
        cleaned, stats = clean_products([])
        assert cleaned == []
        assert stats["input"] == 0
        assert stats["output"] == 0

    def test_invalid_price_kept(self):
        """无效价格商品应保留并排在末尾"""
        p1 = self._make(price=99.0, url="http://x/1")
        p2 = self._make(price=-1.0, url="http://x/2")
        cleaned, stats = clean_products([p1, p2])
        assert len(cleaned) == 2
        assert cleaned[0].price == 99.0
        assert cleaned[1].price == -1.0
        assert stats["invalid_price"] == 1

    def test_empty_title_removed(self):
        p1 = self._make(title="", url="http://x/1")
        p2 = self._make(title="有效", url="http://x/2")
        cleaned, stats = clean_products([p1, p2])
        assert len(cleaned) == 1
        assert stats["empty_title"] == 1

    def test_dedup(self):
        """相同 dedup_key 应去重"""
        p1 = self._make(title="手机", price=99.0, url="http://x/1")
        p2 = self._make(title="手机", price=99.0, url="http://x/2")
        cleaned, stats = clean_products([p1, p2])
        assert len(cleaned) == 1
        assert stats["duplicates"] == 1

    def test_sort_ascending(self):
        p1 = self._make(price=300.0, url="http://x/1")
        p2 = self._make(price=100.0, url="http://x/2")
        p3 = self._make(price=200.0, url="http://x/3")
        cleaned, _ = clean_products([p1, p2, p3])
        assert [p.price for p in cleaned] == [100.0, 200.0, 300.0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
