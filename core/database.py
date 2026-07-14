"""
SQLite 历史数据存储

存储所有采集到的商品快照, 用于:
1. 价格趋势图 (按商品 URL hash 聚合多日价格)
2. 历史采集记录查询
3. 性价比对比基线

采用 sqlite3 标准库, 无需额外 ORM 依赖。
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import DBConfig, get_config
from core.models import Product


# 模块级线程锁 (SQLite 默认连接非线程安全)
_lock = threading.Lock()


class Database:
    """SQLite 历史数据库封装"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS products (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword         TEXT    NOT NULL,
        platform        TEXT    NOT NULL,
        title           TEXT    NOT NULL,
        price           REAL    NOT NULL,
        sales           INTEGER NOT NULL,
        shop            TEXT    NOT NULL DEFAULT '',
        shop_rating     REAL    NOT NULL DEFAULT -1,
        url             TEXT    NOT NULL DEFAULT '',
        url_hash        TEXT    NOT NULL DEFAULT '',
        image_url       TEXT    NOT NULL DEFAULT '',
        sku_id          TEXT    NOT NULL DEFAULT '',
        fetched_at      TEXT    NOT NULL,
        fetched_date    TEXT    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_url_hash ON products(url_hash);
    CREATE INDEX IF NOT EXISTS idx_keyword  ON products(keyword);
    CREATE INDEX IF NOT EXISTS idx_date     ON products(fetched_date);
    CREATE INDEX IF NOT EXISTS idx_keyword_date ON products(keyword, fetched_date DESC, fetched_at DESC);

    CREATE TABLE IF NOT EXISTS crawl_meta (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword         TEXT    NOT NULL,
        platform        TEXT    NOT NULL,
        used_mock       INTEGER NOT NULL DEFAULT 0,
        error           TEXT    NOT NULL DEFAULT '',
        elapsed         REAL    NOT NULL DEFAULT 0,
        created_at      TEXT    NOT NULL
    );
    """

    def __init__(self, cfg: Optional[DBConfig] = None) -> None:
        self.cfg = cfg or get_config().db
        Path(self.cfg.path).parent.mkdir(parents=True, exist_ok=True)
        # 使用长连接复用，避免每次操作都创建/关闭连接
        self._db_conn: Optional[sqlite3.Connection] = None
        self._init_schema()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    @property
    def _connection(self) -> sqlite3.Connection:
        """获取复用的数据库连接 (懒初始化, 线程安全通过 _lock 保护写入)"""
        if self._db_conn is None:
            self._db_conn = sqlite3.connect(
                self.cfg.path, timeout=30, check_same_thread=False
            )
            self._db_conn.row_factory = sqlite3.Row
        return self._db_conn

    @contextmanager
    def _conn(self):
        """获取数据库连接 (上下文管理, 自动提交/回滚)"""
        conn = self._connection
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        """初始化数据库 schema"""
        with self._conn() as conn:
            conn.executescript(self.SCHEMA)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def save_products(self, keyword: str, products: List[Product]) -> int:
        """
        批量保存商品快照

        Args:
            keyword: 搜索关键词
            products: 商品列表

        Returns:
            成功写入的条数
        """
        if not products:
            return 0
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        rows = [
            (
                keyword,
                p.platform,
                p.title,
                p.price,
                p.sales,
                p.shop,
                p.shop_rating,
                p.url,
                p.url_hash,
                p.image_url,
                p.sku_id,
                now.isoformat(timespec="seconds"),
                date_str,
            )
            for p in products
        ]
        with self._conn() as conn:
            with _lock:
                conn.executemany(
                    """INSERT INTO products
                       (keyword, platform, title, price, sales, shop, shop_rating,
                        url, url_hash, image_url, sku_id, fetched_at, fetched_date)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    rows,
                )
        return len(rows)

    def save_meta(self, keyword: str, platform: str, used_mock: bool,
                  error: str, elapsed: float) -> None:
        """记录采集任务元信息"""
        with self._conn() as conn:
            with _lock:
                conn.execute(
                    """INSERT INTO crawl_meta
                       (keyword, platform, used_mock, error, elapsed, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (keyword, platform, int(used_mock), error, elapsed,
                     datetime.now().isoformat(timespec="seconds")),
                )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_latest_by_keyword(self, keyword: str) -> List[Product]:
        """
        获取某关键词最近一次采集的所有商品 (按 url_hash + 最新 fetched_at)

        Args:
            keyword: 搜索关键词

        Returns:
            Product 列表
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM products
                   WHERE keyword = ?
                   ORDER BY fetched_date DESC, fetched_at DESC
                   LIMIT 1000""",
                (keyword,),
            ).fetchall()
        if not rows:
            return []
        # 取最新 fetched_at 对应的记录
        latest_at = rows[0]["fetched_at"]
        return [self._row_to_product(r) for r in rows if r["fetched_at"] == latest_at]

    def get_price_trend(self, url_hash: str, days: int = 30) -> List[Tuple[str, float]]:
        """
        查询某商品最近 N 天的价格趋势

        Args:
            url_hash: 商品 URL 哈希
            days: 天数

        Returns:
            [(date_str, min_price), ...] 按日期升序, 取当日最低价
        """
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT fetched_date, MIN(price) AS price
                   FROM products
                   WHERE url_hash = ? AND fetched_date >= ?
                   GROUP BY fetched_date
                   ORDER BY fetched_date ASC""",
                (url_hash, since),
            ).fetchall()
        return [(r["fetched_date"], r["price"]) for r in rows]

    def get_trend_for_keyword(self, keyword: str, days: int = 30) -> Dict[str, List[Tuple[str, float]]]:
        """
        批量查询关键词下所有商品的价格趋势

        Returns:
            {url_hash: [(date, price), ...], ...}
        """
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT url_hash, fetched_date, MIN(price) AS price
                   FROM products
                   WHERE keyword = ? AND fetched_date >= ? AND url_hash != ''
                   GROUP BY url_hash, fetched_date
                   ORDER BY url_hash, fetched_date""",
                (keyword, since),
            ).fetchall()
        result: Dict[str, List[Tuple[str, float]]] = {}
        for r in rows:
            result.setdefault(r["url_hash"], []).append((r["fetched_date"], r["price"]))
        return result

    def list_keywords(self, limit: int = 50) -> List[Tuple[str, str]]:
        """列出最近采集的关键词及时间"""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT keyword, MAX(fetched_at) AS last
                   FROM products GROUP BY keyword ORDER BY last DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [(r["keyword"], r["last"]) for r in rows]

    def count_total(self) -> int:
        """总记录数"""
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------
    def cleanup_old(self, retention_days: int) -> int:
        """
        清理超过保留期的历史记录

        Args:
            retention_days: 保留天数, 0 表示不清理

        Returns:
            删除条数
        """
        if retention_days <= 0:
            return 0
        cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        with self._conn() as conn:
            with _lock:
                cur = conn.execute(
                    "DELETE FROM products WHERE fetched_date < ?", (cutoff,)
                )
                return cur.rowcount

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_product(row: sqlite3.Row) -> Product:
        return Product(
            platform=row["platform"],
            title=row["title"],
            price=row["price"],
            sales=row["sales"],
            shop=row["shop"],
            shop_rating=row["shop_rating"],
            url=row["url"],
            image_url=row["image_url"],
            sku_id=row["sku_id"],
            fetched_at=row["fetched_at"],
        )


__all__ = ["Database"]
