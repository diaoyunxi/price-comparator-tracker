#!/usr/bin/env python3
"""
电商商品价格自动化采集与对比工具 - 命令行入口

功能:
- 按关键词批量采集京东/淘宝/拼多多商品
- 自动清洗去重排序
- 性价比推荐
- 生成 CSV/JSON 导出
- 生成 matplotlib 图表
- 历史价格趋势查询

示例:
    # 标准采集 (真实爬虫 + Mock 回退)
    python cli.py search 蓝牙耳机

    # 仅 Mock 数据快速演示
    python cli.py search 蓝牙耳机 --mock

    # 指定平台与数量
    python cli.py search 机械键盘 --platforms jd,pdd --limit 20

    # 导出 CSV 与图表
    python cli.py search 蓝牙耳机 --export csv --chart

    # 查看某商品价格趋势
    python cli.py trend --url-hash abc123def456

    # 列出历史关键词
    python cli.py history
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

# 让 `python cli.py` 直接运行时也能找到包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import get_config, read_version, EXPORT_DIR
from core.database import Database
from core.runner import run_crawl


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# ---------------------------------------------------------------------------
# Rich 表格渲染 (缺失时退化 plain text)
# ---------------------------------------------------------------------------
def _render_table(headers: List[str], rows: List[List[str]], title: str = "") -> None:
    """渲染表格, 优先 rich, 缺失则退化"""
    try:
        from rich.console import Console
        from rich.table import Table
        console = Console()
        table = Table(title=title, show_lines=False, header_style="bold magenta")
        for h in headers:
            table.add_column(h, overflow="fold")
        for row in rows:
            table.add_row(*[str(c) for c in row])
        console.print(table)
        return
    except ImportError:
        pass

    # 退化: 简单对齐
    print(f"\n== {title} ==")
    print(" | ".join(headers))
    print("-" * 80)
    for row in rows:
        print(" | ".join(str(c) for c in row))


def _platform_name(plat: str) -> str:
    return get_config().platforms.get(plat, plat)


# ---------------------------------------------------------------------------
# 命令: search
# ---------------------------------------------------------------------------
def cmd_search(args: argparse.Namespace) -> int:
    """执行采集并展示结果"""
    cfg = get_config()
    platforms = args.platforms.split(",") if args.platforms else list(cfg.platforms.keys())
    platforms = [p.strip() for p in platforms if p.strip()]

    db = Database() if not args.no_db else None

    print(f"\n[1/4] 关键词: {args.keyword}")
    print(f"[2/4] 平台: {', '.join(_platform_name(p) for p in platforms)} (共 {len(platforms)} 个)")
    print(f"[3/4] 每平台采集: {args.limit} 条, 模式: {'Mock' if args.mock else '真实(失败回退Mock)'}")
    print("[4/4] 开始采集...\n")

    result = run_crawl(
        keyword=args.keyword,
        platforms=platforms,
        limit_per_platform=args.limit,
        use_mock=args.mock,
        db=db,
        parallel=not args.serial,
    )

    # ------------------------------------------------------------------
    # 1. 采集摘要
    # ------------------------------------------------------------------
    _render_table(
        ["平台", "采集数", "Mock回退", "耗时(s)", "错误"],
        [[r["platform"], len(r.get("products", [])),
          "是" if r.get("used_mock") else "否",
          r.get("elapsed", 0), r.get("error", "")[:30]]
         for r in result.raw_results],
        title="采集摘要",
    )

    # ------------------------------------------------------------------
    # 2. 清洗统计
    # ------------------------------------------------------------------
    cs = result.clean_stats
    print(f"\n清洗: 输入 {cs.get('input', 0)} -> 输出 {cs.get('output', 0)} "
          f"(无效价格 {cs.get('invalid_price', 0)}, 重复 {cs.get('duplicates', 0)})")

    # ------------------------------------------------------------------
    # 3. 商品对比表 (按价格升序)
    # ------------------------------------------------------------------
    show_n = min(args.show, len(result.products))
    if show_n > 0:
        rows = []
        for p in result.products[:show_n]:
            rows.append([
                _platform_name(p.platform),
                p.title[:35] + ("..." if len(p.title) > 35 else ""),
                f"¥{p.price:.2f}" if p.price > 0 else "N/A",
                f"{p.sales:,}" if p.sales >= 0 else "N/A",
                p.shop[:18],
                f"{p.shop_rating:.1f}" if p.shop_rating >= 0 else "N/A",
            ])
        _render_table(
            ["平台", "商品标题", "价格", "销量", "店铺", "评分"],
            rows,
            title=f"商品横向对比 (按价格升序, 共 {len(result.products)} 条, 显示前 {show_n})",
        )

    # ------------------------------------------------------------------
    # 4. 平台统计
    # ------------------------------------------------------------------
    if result.platform_stats:
        rows = [[s.platform, s.count, f"¥{s.avg_price:.2f}",
                 f"¥{s.min_price:.2f}", f"¥{s.max_price:.2f}",
                 f"{s.avg_sales:,}", f"{s.avg_rating:.2f}"]
                for s in result.platform_stats]
        _render_table(
            ["平台", "条数", "均价", "最低", "最高", "均销量", "均评分"],
            rows,
            title="平台统计对比",
        )

    # ------------------------------------------------------------------
    # 5. 价差信息
    # ------------------------------------------------------------------
    if result.cheapest and result.most_expensive:
        print("\n价差分析:")
        print(f"  最便宜: [{_platform_name(result.cheapest.platform)}] "
              f"{result.cheapest.title[:30]} ¥{result.cheapest.price:.2f}")
        print(f"  最贵:   [{_platform_name(result.most_expensive.platform)}] "
              f"{result.most_expensive.title[:30]} ¥{result.most_expensive.price:.2f}")
        print(f"  价差:   ¥{result.price_gap:.2f} ({result.price_gap_ratio:.1f}%)")

    # ------------------------------------------------------------------
    # 6. 性价比推荐
    # ------------------------------------------------------------------
    if result.recommendations:
        rows = []
        for rec in result.recommendations:
            p = rec.product
            rows.append([
                f"#{rec.rank}",
                _platform_name(p.platform),
                p.title[:30] + ("..." if len(p.title) > 30 else ""),
                f"¥{p.price:.2f}" if p.price > 0 else "N/A",
                f"{p.sales:,}" if p.sales >= 0 else "N/A",
                f"{rec.score:.1f}",
                rec.reason,
            ])
        _render_table(
            ["排名", "平台", "商品", "价格", "销量", "综合分", "推荐理由"],
            rows,
            title="性价比推荐 Top N",
        )

    # ------------------------------------------------------------------
    # 7. 导出
    # ------------------------------------------------------------------
    if args.export:
        _export(result, args.export)
    if args.chart:
        _generate_charts(result, db, args.trend_days)
    if args.save_json:
        out = EXPORT_DIR / f"result_{args.keyword}_{int(time.time())}.json"
        out.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                      encoding="utf-8")
        print(f"\n结果 JSON 已保存: {out}")

    print(f"\n总耗时: {result.elapsed:.2f}s")
    return 0


def _export(result, fmt: str) -> None:
    """导出 CSV / JSON"""
    from core.compare import build_compare_table
    if fmt == "csv":
        import csv
        out = EXPORT_DIR / f"products_{result.keyword}_{int(time.time())}.csv"
        rows = build_compare_table(result.products)
        if not rows:
            print("无数据可导出")
            return
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        print(f"CSV 已导出: {out}")
    elif fmt == "json":
        out = EXPORT_DIR / f"products_{result.keyword}_{int(time.time())}.json"
        out.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                      encoding="utf-8")
        print(f"JSON 已导出: {out}")


def _generate_charts(result, db, trend_days: int) -> None:
    """生成图表"""
    try:
        from viz.charts import (
            chart_platform_price_box,
            chart_price_distribution,
            chart_platform_avg,
            chart_price_trend,
        )
    except ImportError as e:
        print(f"可视化模块未安装: {e}")
        return
    from config import get_config
    cfg = get_config()

    print("\n生成图表中...")
    p1 = chart_platform_price_box(result.products, cfg.platforms)
    p2 = chart_price_distribution(result.products)
    p3 = chart_platform_avg(result.platform_stats)
    if p1:
        print(f"  [OK] 平台价格箱线图: {p1}")
    if p2:
        print(f"  [OK] 价格分布图: {p2}")
    if p3:
        print(f"  [OK] 平台均价图: {p3}")

    # 趋势图 (取最便宜商品)
    if db and result.cheapest and result.cheapest.url_hash:
        p4 = chart_price_trend(db, result.cheapest.url_hash,
                              result.cheapest.title[:30], days=trend_days)
        if p4:
            print(f"  [OK] 价格趋势图: {p4}")


# ---------------------------------------------------------------------------
# 命令: trend
# ---------------------------------------------------------------------------
def cmd_trend(args: argparse.Namespace) -> int:
    """查询商品价格趋势"""
    db = Database()
    if not args.url_hash:
        # 列出所有商品 url_hash 供选择
        rows = db.list_keywords()
        if not rows:
            print("数据库无历史记录")
            return 0
        print("最近采集关键词:")
        for kw, ts in rows[:10]:
            print(f"  {kw}  ({ts})")
        print("\n用法: python cli.py trend --keyword <关键词>")
        return 0

    trend = db.get_price_trend(args.url_hash, args.days)
    if not trend:
        print("无趋势数据")
        return 0
    print(f"\n价格趋势 (近 {args.days} 天):")
    # 过滤有效价格，避免除零崩溃
    prices = [p for _, p in trend if p > 0]
    for date, price in trend:
        bar = "█" * int(price / max(prices) * 30) if price > 0 and prices else ""
        print(f"  {date}  ¥{price:>10.2f}  {bar}")
    return 0


# ---------------------------------------------------------------------------
# 命令: history
# ---------------------------------------------------------------------------
def cmd_history(args: argparse.Namespace) -> int:
    """列出历史采集记录"""
    db = Database()
    print(f"\n数据库总记录数: {db.count_total()}")
    rows = db.list_keywords(args.limit)
    if not rows:
        print("无历史记录")
        return 0
    print(f"\n最近 {len(rows)} 个关键词:")
    _render_table(["关键词", "最后采集时间"], [[k, t] for k, t in rows],
                 title="采集历史")
    return 0


# ---------------------------------------------------------------------------
# 命令: demo
# ---------------------------------------------------------------------------
def cmd_demo(args: argparse.Namespace) -> int:
    """使用 Mock 数据快速演示完整流程"""
    args.keyword = args.keyword or "蓝牙耳机"
    args.mock = True
    args.limit = args.limit or 30
    args.show = args.show or 10
    args.chart = True
    args.no_db = False
    args.export = None
    args.save_json = False
    args.trend_days = 30
    args.platforms = None
    args.serial = False
    return cmd_search(args)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="price-comparator",
        description="电商商品价格自动化采集与对比工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="更多文档见 README.md",
    )
    parser.add_argument("-V", "--version", action="version",
                       version=f"price-comparator {read_version()}")
    parser.add_argument("-v", "--verbose", action="store_true",
                       help="开启 DEBUG 日志")

    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    # search
    p_search = sub.add_parser("search", help="按关键词采集并对比")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--platforms", default="",
                         help="平台列表 (逗号分隔), 默认全部: jd,taobao,pdd")
    p_search.add_argument("--limit", type=int, default=30,
                         help="每平台采集条数 (默认 30)")
    p_search.add_argument("--mock", action="store_true",
                         help="仅使用 Mock 数据 (跳过真实爬虫)")
    p_search.add_argument("--serial", action="store_true",
                         help="串行采集 (调试用)")
    p_search.add_argument("--show", type=int, default=10,
                         help="展示前 N 条商品 (默认 10)")
    p_search.add_argument("--export", choices=["csv", "json"],
                         help="导出格式")
    p_search.add_argument("--chart", action="store_true",
                         help="生成 matplotlib 图表")
    p_search.add_argument("--save-json", action="store_true",
                         help="保存完整结果 JSON")
    p_search.add_argument("--trend-days", type=int, default=30,
                         help="趋势图天数")
    p_search.add_argument("--no-db", action="store_true",
                         help="不写入数据库")
    p_search.set_defaults(func=cmd_search)

    # trend
    p_trend = sub.add_parser("trend", help="查看商品价格趋势")
    p_trend.add_argument("--url-hash", default="",
                         help="商品 URL 哈希 (省略则列出关键词)")
    p_trend.add_argument("--keyword", default="",
                         help="按关键词查最近商品 url_hash")
    p_trend.add_argument("--days", type=int, default=30,
                         help="趋势天数")
    p_trend.set_defaults(func=cmd_trend)

    # history
    p_hist = sub.add_parser("history", help="列出历史采集记录")
    p_hist.add_argument("--limit", type=int, default=20)
    p_hist.set_defaults(func=cmd_history)

    # demo
    p_demo = sub.add_parser("demo", help="Mock 数据快速演示")
    p_demo.add_argument("--keyword", default="蓝牙耳机")
    p_demo.add_argument("--limit", type=int, default=30)
    p_demo.add_argument("--show", type=int, default=10)
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已取消")
        return 130
    except Exception as e:
        logging.getLogger("cli").exception("执行失败: %s", e)
        print(f"\n[ERROR] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
