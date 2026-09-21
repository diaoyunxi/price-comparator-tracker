"""
拼多多爬虫

实现策略:
1. 优先尝试移动端 H5 (mobile.yangkeduo.com/search)
2. 备用: API 接口 (mobile.yangkeduo.com/proxy/api/api/goods/v2/search)
3. 全部失败由 BaseScraper 自动回退 Mock

注意: 拼多多移动端 H5 反爬极强, 多数请求会返回 302 跳转或滑块验证。
本爬虫仅做轻量尝试。
"""

from __future__ import annotations

import json
import logging
import re
from typing import List
from urllib.parse import quote

from bs4 import BeautifulSoup

from core.models import Product
from scrapers.base import BaseScraper


logger = logging.getLogger("scraper.pdd")


class PddScraper(BaseScraper):
    """拼多多爬虫"""

    platform = "pdd"
    platform_name = "拼多多"

    def _do_search(self, keyword: str, limit: int) -> List[Product]:
        """
        拼多多搜索: 优先移动端 H5

        Args:
            keyword: 关键词
            limit: 上限

        Returns:
            Product 列表
        """
        # 1. 移动端搜索页 (HTML)
        url = f"https://mobile.yangkeduo.com/search_result.html?search_key={quote(keyword)}"
        result = self.session.get(url, platform="pdd",
                                 referer="https://mobile.yangkeduo.com/")
        self._sleep()
        if result.success:
            products = self._parse_mobile_h5(result.text, keyword, limit)
            if products:
                return products
            # 尝试从嵌入 JSON 提取
            products = self._extract_embedded_json(result.text, keyword, limit)
            if products:
                return products

        # 2. 备用 API 接口
        api_url = "https://mobile.yangkeduo.com/proxy/api/api/goods/v2/search"
        params = {
            "search_key": keyword,
            "page": 1,
            "size": limit,
            "sort": "default",
        }
        result2 = self.session.get(api_url, platform="pdd",
                                   referer="https://mobile.yangkeduo.com/",
                                   params=params)
        self._sleep()
        if result2.success:
            products = self._parse_api_json(result2.text, keyword, limit)
            if products:
                return products

        return []

    # ------------------------------------------------------------------
    # 解析逻辑
    # ------------------------------------------------------------------
    def _parse_mobile_h5(self, html: str, keyword: str, limit: int = 30) -> List[Product]:
        """解析移动端 H5 搜索结果"""
        products: List[Product] = []
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # 拼多多 H5 商品卡片常见类名
        items = soup.select("div[data-goods-id], div.goods-item, li.item, div.r-search-item")
        if not items:
            items = soup.find_all(["div", "li"],
                                 class_=re.compile(r"(goods|item|product|search)", re.I))

        for el in items:
            try:
                goods_id = el.get("data-goods-id") or el.get("data-id") or ""
                # 标题
                title_el = el.select_one(".goods-title, .title, .item-title, .r-title, [class*=title]")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 3:
                    continue
                # 价格
                price = -1.0
                price_el = el.select_one(".price, .r-price, [class*=price]")
                if price_el:
                    from core.dedup import parse_price
                    price = parse_price(price_el.get_text(strip=True))
                # 链接
                url = ""
                if goods_id:
                    url = f"https://mobile.yangkeduo.com/goods.html?goods_id={goods_id}"
                else:
                    link = el.select_one("a[href]")
                    if link:
                        href = link.get("href", "")
                        if href and not href.startswith("javascript"):
                            url = href if href.startswith("http") else f"https:{href}" if href.startswith("//") else f"https://mobile.yangkeduo.com{href}"
                # 销量
                sales = -1
                sales_el = el.select_one(".sales, .r-sales, [class*=sale]")
                if sales_el:
                    from core.dedup import parse_sales
                    sales = parse_sales(sales_el.get_text(strip=True))
                # 店铺
                shop_el = el.select_one(".mall, .shop, .store, [class*=shop]")
                shop = shop_el.get_text(strip=True) if shop_el else "拼多多商家"

                products.append(Product(
                    platform=self.platform,
                    title=title, price=price, sales=sales,
                    shop=shop, shop_rating=-1.0,
                    url=url, sku_id=str(goods_id),
                ))
                if len(products) >= limit:
                    break
            except Exception as e:
                logger.debug("[%s] 解析单条商品失败: %s", self.platform, e)
                continue
        return products

    def _extract_embedded_json(self, html: str, keyword: str, limit: int = 30) -> List[Product]:
        """从 HTML 中提取嵌入的 JSON 数据"""
        products: List[Product] = []
        # 拼多多常把数据放在 window.__INITIAL_STATE__ 中
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>",
                     html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                # 递归查找商品列表
                items = _find_goods_list(data)
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    title = it.get("goodsName") or it.get("title") or ""
                    if not title:
                        continue
                    price = it.get("price") or it.get("minPrice") or -1
                    sales = it.get("sales") or it.get("salesTip") or -1
                    goods_id = str(it.get("goodsId") or it.get("id") or "")
                    products.append(Product(
                        platform=self.platform,
                        title=title,
                        price=float(price) if price else -1.0,
                        sales=int(sales) if isinstance(sales, int) else _parse_sales_str(sales),
                        shop=it.get("mallName") or "拼多多商家",
                        shop_rating=-1.0,
                        url=f"https://mobile.yangkeduo.com/goods.html?goods_id={goods_id}" if goods_id else "",
                        sku_id=goods_id,
                    ))
                if products:
                    return products[:limit]
            except Exception as e:
                logger.debug("[%s] __INITIAL_STATE__ 解析失败: %s", self.platform, e)
        return products

    def _parse_api_json(self, text: str, keyword: str, limit: int = 30) -> List[Product]:
        """解析 API JSON 响应"""
        products: List[Product] = []
        try:
            data = json.loads(text)
        except Exception as e:
            logger.debug("[%s] JSON 解析失败: %s", self.platform, e)
            return []
        # 拼多多 API 通常返回 {error_code: 0, result: {list: [...]}}
        items = []
        if isinstance(data, dict):
            for k in ("result", "data"):
                if isinstance(data.get(k), dict):
                    for kk in ("list", "items", "goods_list"):
                        if isinstance(data[k].get(kk), list):
                            items = data[k][kk]
                            break
                if items:
                    break
            if not items and isinstance(data.get("list"), list):
                items = data["list"]

        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                title = it.get("goodsName") or it.get("goods_name") or ""
                if not title:
                    continue
                price = it.get("price") or it.get("min_normal_price") or -1
                # 拼多多 API 价格可能以分为单位 (整数且无小数点时大概率是分)
                # 价格 > 10000 分 (即 100 元以上) 且为整数时视为分单位
                if isinstance(price, (int, float)) and price > 0 and price >= 10000 and price == int(price):
                    price = price / 100
                goods_id = str(it.get("goodsId") or it.get("goods_id") or "")
                products.append(Product(
                    platform=self.platform,
                    title=title,
                    price=float(price) if price else -1.0,
                    sales=_parse_sales_str(it.get("sales") or it.get("salesTip") or ""),
                    shop=it.get("mallName") or it.get("mall_name") or "拼多多商家",
                    shop_rating=-1.0,
                    url=f"https://mobile.yangkeduo.com/goods.html?goods_id={goods_id}" if goods_id else "",
                    sku_id=goods_id,
                ))
                if len(products) >= limit:
                    break
            except Exception as e:
                logger.debug("[%s] 单条商品解析失败: %s", self.platform, e)
                continue
        return products


def _parse_sales_str(s) -> int:
    """解析 "已拼1.2万件" 等格式"""
    if not s:
        return -1
    if isinstance(s, (int, float)):
        return int(s)
    from core.dedup import parse_sales
    return parse_sales(str(s))


def _find_goods_list(data, depth=0):
    """递归查找商品列表"""
    if depth > 8:
        return []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        # 启发式: 元素包含 goodsName / goodsId / title 之一
        if any("goodsName" in x or "goodsId" in x or "goods_name" in x
               for x in data[:3] if isinstance(x, dict)):
            return data
        return []
    if isinstance(data, dict):
        for v in data.values():
            r = _find_goods_list(v, depth + 1)
            if r:
                return r
    return []


__all__ = ["PddScraper"]
