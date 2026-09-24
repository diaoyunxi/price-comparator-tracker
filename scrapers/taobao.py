"""
淘宝爬虫

实现策略:
1. 优先尝试移动端 H5 搜索 (s.m.taobao.com)
2. 备用: API JSON 接口 (mtop.taobao.wireless.search.app)
3. 全部失败由 BaseScraper 自动回退 Mock

注意: 淘宝反爬极强, 未登录态下接口几乎全部返回 403 / 滑块验证。
本爬虫仅做轻量尝试, 失败即回退, 不持久重试避免被风控。
"""

from __future__ import annotations

import json
import logging
import re

from urllib.parse import quote

from bs4 import BeautifulSoup

from core.models import Product
from scrapers.base import BaseScraper


logger = logging.getLogger("scraper.taobao")


class TaobaoScraper(BaseScraper):
    """淘宝爬虫"""

    platform = "taobao"
    platform_name = "淘宝"

    def _do_search(self, keyword: str, limit: int) -> list[Product]:
        """
        淘宝搜索: 优先移动端 H5

        Args:
            keyword: 关键词
            limit: 上限

        Returns:
            Product 列表
        """
        # 1. 移动端搜索页 (HTML)
        url = f"https://s.m.taobao.com/h5?&q={quote(keyword)}&search=y&from=1"
        result = self.session.get(url, platform="taobao",
                                 referer="https://s.m.taobao.com/")
        self._sleep()
        if result.success:
            products = self._parse_mobile_h5(result.text, keyword, limit)
            if products:
                return products

        # 2. 尝试从 HTML 中提取嵌入的 JSON 数据 (常见 mtop 响应)
        if result.success:
            products = self._extract_embedded_json(result.text, keyword, limit)
            if products:
                return products

        # 3. PC 端搜索 (基本会被重定向到登录)
        logger.debug("[%s] 移动端无结果, 尝试 PC 端", self.platform)
        url2 = f"https://s.taobao.com/search?q={quote(keyword)}&imgfile=&js=1&stats_click=search_radio_all%3A1"
        result2 = self.session.get(url2, platform="taobao",
                                  referer="https://www.taobao.com/")
        self._sleep()
        if result2.success:
            products = self._extract_embedded_json(result2.text, keyword, limit)
            if products:
                return products

        return []

    # ------------------------------------------------------------------
    # 解析逻辑
    # ------------------------------------------------------------------
    def _parse_mobile_h5(self, html: str, keyword: str, limit: int = 30) -> list[Product]:
        """解析移动端 H5 搜索结果"""
        products: list[Product] = []
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # 兼容多种容器类名
        items = soup.select("div.item, li.item, div.product, div.Card, div[data-spm]")
        if not items:
            items = soup.find_all(["div", "li"],
                                 class_=re.compile(r"(item|product|goods|card)", re.I))

        for el in items:
            try:
                # 标题
                title_el = el.select_one("a.title, .title, .item-title, .p-title, h4, h3")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 4:
                    continue
                # 价格
                price = -1.0
                price_el = el.select_one(".price, .item-price, .p-price, [class*=price]")
                if price_el:
                    from core.dedup import parse_price
                    price = parse_price(price_el.get_text(strip=True))
                # 链接
                url = ""
                link = el.select_one("a[href]")
                if link:
                    href = link.get("href", "")
                    if href and not href.startswith("javascript"):
                        if href.startswith("//"):
                            url = f"https:{href}"
                        elif href.startswith("http"):
                            url = href
                # 商品 ID
                sku_id = ""
                m = re.search(r"(?:id=|item/)(\d+)", url)
                if m:
                    sku_id = m.group(1)
                # 销量
                sales = -1
                sales_el = el.select_one(".sale, .sales, .sold, [class*=sale]")
                if sales_el:
                    from core.dedup import parse_sales
                    sales = parse_sales(sales_el.get_text(strip=True))
                # 店铺
                shop_el = el.select_one(".shop, .store, .seller, [class*=shop]")
                shop = shop_el.get_text(strip=True) if shop_el else "淘宝商家"

                products.append(Product(
                    platform=self.platform,
                    title=title, price=price, sales=sales,
                    shop=shop, shop_rating=-1.0,
                    url=url, sku_id=sku_id,
                ))
                if len(products) >= limit:
                    break
            except Exception as e:
                logger.debug("[%s] 解析单条商品失败: %s", self.platform, e)
                continue
        return products

    def _extract_embedded_json(self, html: str, keyword: str, limit: int = 30) -> list[Product]:
        """
        从 HTML 中提取嵌入的 JSON 数据

        淘宝/天猫页面常把数据放在 <script> 标签中:
        - window.__INITIAL_STATE__ = {...}
        - g_page_config = {...}
        - mtop 返回的 JSONP
        """
        products: list[Product] = []
        # 模式 1: g_page_config
        m = re.search(r"g_page_config\s*=\s*(\{.*?\})\s*[;<\n]", html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                items = (data.get("mods", {})
                            .get("itemlist", {})
                            .get("data", {})
                            .get("auctions", []))
                for it in items:
                    products.append(Product(
                        platform=self.platform,
                        title=it.get("raw_title", ""),
                        price=float(it.get("view_price", -1) or -1),
                        sales=_parse_sales_str(it.get("view_sales", it.get("view_sales_num", ""))),
                        shop=it.get("nick", "淘宝"),
                        shop_rating=float(it.get("shopcard", {}).get("slevel", -1) or -1),
                        url=f"https://item.taobao.com/item.htm?id={it.get('nid','')}",
                        sku_id=str(it.get("nid", "")),
                    ))
                if products:
                    return products[:limit]
            except Exception as e:
                logger.debug("[%s] g_page_config 解析失败: %s", self.platform, e)

        # 模式 2: __INITIAL_STATE__
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                # 路径可能变化, 递归查找包含 item 列表的字段
                items = _find_first_item_list(data, ("auctions", "items", "list", "itemList"))
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    title = it.get("title") or it.get("raw_title") or ""
                    if not title:
                        continue
                    price = it.get("price") or it.get("view_price") or -1
                    products.append(Product(
                        platform=self.platform,
                        title=title,
                        price=float(price) if price else -1.0,
                        sales=_parse_sales_str(it.get("view_sales", it.get("sales", ""))),
                        shop=it.get("shopName") or it.get("nick") or "淘宝",
                        shop_rating=-1.0,
                        url=it.get("url") or f"https://item.taobao.com/item.htm?id={it.get('nid','')}",
                        sku_id=str(it.get("nid") or it.get("itemId") or ""),
                    ))
                if products:
                    return products[:limit]
            except Exception as e:
                logger.debug("[%s] __INITIAL_STATE__ 解析失败: %s", self.platform, e)
        return products


def _parse_sales_str(s) -> int:
    """解析 "月销 1.2万" 等格式"""
    if not s:
        return -1
    from core.dedup import parse_sales
    return parse_sales(str(s))


def _find_first_item_list(data, keys, depth=0):
    """递归查找包含 item 列表的字段"""
    if depth > 8:
        return []
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            return data
        return []
    if isinstance(data, dict):
        for k in keys:
            if k in data and isinstance(data[k], list) and data[k]:
                if isinstance(data[k][0], dict):
                    return data[k]
        for v in data.values():
            r = _find_first_item_list(v, keys, depth + 1)
            if r:
                return r
    return []


__all__ = ["TaobaoScraper"]
