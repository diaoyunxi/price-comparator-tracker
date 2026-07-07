"""
京东爬虫

实现策略:
1. 优先尝试移动端搜索接口 (so.m.jd.com)
2. 失败时尝试 PC 端接口 (search.jd.com)
3. 全部失败时由 BaseScraper.search 自动回退 Mock

注意: 京东价格字段在未登录态下可能缺失, 此时使用页面标注的"参考价"或返回 -1,
由后续清洗/对比逻辑处理。本爬虫仅做轻量尝试, 不绕过登录态。
"""

from __future__ import annotations

import json
import logging
import re
from typing import List
from urllib.parse import quote

from bs4 import BeautifulSoup

from config import get_config
from core.models import Product
from scrapers.base import BaseScraper


logger = logging.getLogger("scraper.jd")


class JDScraper(BaseScraper):
    """京东爬虫"""

    platform = "jd"
    platform_name = "京东"

    def _do_search(self, keyword: str, limit: int) -> List[Product]:
        """
        京东搜索: 优先移动端 H5

        Args:
            keyword: 关键词
            limit: 上限

        Returns:
            Product 列表 (空表示失败)
        """
        # 1. 移动端 H5 搜索页
        url = f"https://so.m.jd.com/ware/search.action?keyword={quote(keyword)}&page=1"
        result = self.session.get(url, platform="jd",
                                 referer="https://so.m.jd.com/")
        self._sleep()
        if result.success:
            products = self._parse_mobile_h5(result.text, keyword)
            if products:
                return products

        # 2. 尝试 PC 端 (JSON 接口, 多数情况下未登录会被拦截)
        logger.debug("[%s] 移动端无结果, 尝试 PC 端", self.platform)
        url2 = f"https://search.jd.com/Search?keyword={quote(keyword)}&enc=utf-8"
        result2 = self.session.get(url2, platform="jd",
                                  referer="https://www.jd.com/")
        self._sleep()
        if result2.success:
            products = self._parse_pc(result2.text, keyword)
            if products:
                return products

        return []

    # ------------------------------------------------------------------
    # 解析逻辑
    # ------------------------------------------------------------------
    def _parse_mobile_h5(self, html: str, keyword: str) -> List[Product]:
        """
        解析移动端 H5 搜索结果

        页面结构: 商品卡片在 <li class="search_item"> 或类似容器中
        价格: <em class="search_price">¥99.50</em>
        标题: <div class="search_p_title"><a>...</a></div>
        链接: <a href="//item.m.jd.com/product/12345.html">
        """
        products: List[Product] = []
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # 兼容多种选择器
        items = soup.select("li.search_item, div.goods_item, li.gl-item, div.search_item")
        if not items:
            # 退化: 通用提取所有带价格的卡片
            items = soup.find_all(["li", "div"],
                                 class_=re.compile(r"(item|goods|product)", re.I))

        for el in items:
            try:
                # 标题
                title_el = el.select_one("a, .search_p_title, .p-name, .title, .goods_name")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue
                # 价格
                price = -1.0
                price_el = el.select_one(".search_price, .p-price, .price, .goods_price")
                if price_el:
                    from core.dedup import parse_price
                    price = parse_price(price_el.get_text(strip=True))
                # 链接
                url = ""
                link = el.select_one("a[href]")
                if link:
                    href = link.get("href", "")
                    if href and not href.startswith("javascript"):
                        url = href if href.startswith("http") else f"https:{href}" if href.startswith("//") else f"https://so.m.jd.com{href}"
                # SKU ID
                sku_id = ""
                m = re.search(r"product/(\d+)", url)
                if m:
                    sku_id = m.group(1)
                # 销量/店铺 (移动端通常缺失)
                sales_text = el.select_one(".search_comment, .comment, .sales")
                sales = -1
                if sales_text:
                    from core.dedup import parse_sales
                    sales = parse_sales(sales_text.get_text(strip=True))
                shop_el = el.select_one(".search_shop, .shop, .store")
                shop = shop_el.get_text(strip=True) if shop_el else "京东自营"

                products.append(Product(
                    platform=self.platform,
                    title=title,
                    price=price,
                    sales=sales,
                    shop=shop,
                    shop_rating=-1.0,
                    url=url,
                    sku_id=sku_id,
                ))
                if len(products) >= self.cfg.limit_per_platform:
                    break
            except Exception as e:
                logger.debug("[%s] 解析单条商品失败: %s", self.platform, e)
                continue
        return products

    def _parse_pc(self, html: str, keyword: str) -> List[Product]:
        """
        解析 PC 端搜索结果页 (备用)

        京东 PC 页中商品数据常嵌入 <script> 中的 glb/jsonp 变量
        """
        products: List[Product] = []
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # 尝试从 glb 变量提取 (京东常见)
        for script in soup.find_all("script"):
            text = script.string or ""
            # 查找 window.__INITIAL_STATE__ 或类似 JSON 数据
            m = re.search(r"searchInfo\s*[:=]\s*(\[.*?\])\s*[;<]", text, re.S)
            if m:
                try:
                    data = json.loads(m.group(1))
                    for it in data:
                        products.append(self._item_from_pc_json(it))
                except Exception:
                    pass
                if products:
                    return products[:self.cfg.limit_per_platform]

        # 退化: 通用选择器
        for el in soup.select("li.gl-item, div.gl-item"):
            try:
                title_el = el.select_one(".p-name em, .p-name a")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue
                price_el = el.select_one(".p-price i, .p-price strong")
                price = -1.0
                if price_el:
                    from core.dedup import parse_price
                    price = parse_price(price_el.get_text(strip=True))
                link_el = el.select_one(".p-name a")
                url = ""
                sku_id = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href:
                        url = href if href.startswith("http") else f"https:{href}" if href.startswith("//") else f"https:{href}"
                    m = re.search(r"product/(\d+)", url)
                    if m:
                        sku_id = m.group(1)
                shop_el = el.select_one(".p-shop a, .p-shop")
                shop = shop_el.get_text(strip=True) if shop_el else "京东"
                products.append(Product(
                    platform=self.platform,
                    title=title, price=price, sales=-1,
                    shop=shop, shop_rating=-1.0,
                    url=url, sku_id=sku_id,
                ))
                if len(products) >= self.cfg.limit_per_platform:
                    break
            except Exception:
                continue
        return products

    def _item_from_pc_json(self, it: dict) -> Product:
        """从 PC 端 JSON 数据项构造 Product"""
        return Product(
            platform=self.platform,
            title=it.get("wname", it.get("title", "")),
            price=float(it.get("jd_price", it.get("price", -1)) or -1),
            sales=int(it.get("commentcount", -1) or -1),
            shop=it.get("shop_name", "京东"),
            shop_rating=-1.0,
            url=f"https://item.jd.com/{it.get('sku_id','')}.html",
            sku_id=str(it.get("sku_id", "")),
        )


__all__ = ["JDScraper"]
