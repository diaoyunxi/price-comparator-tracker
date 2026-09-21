"""
图表生成模块 (CLI 用, matplotlib)

提供 4 类图表 PNG 输出:
1. 平台价格对比箱线图
2. 商品价格分布柱状图
3. 历史价格趋势折线图
4. 平台均价对比柱状图

中文字体自动检测: 优先 Microsoft YaHei / PingFang SC / Noto Sans CJK / SimHei,
全部缺失时退化英文标签, 不阻塞绘图。

注意: 当前所有图表生成函数均为同步阻塞调用 (matplotlib 使用 Agg 后端)。
在 Web 异步场景下, 建议通过 loop.run_in_executor 将这些函数放入线程池执行,
避免阻塞事件循环。后续可考虑提供 async 异步生成图表的封装版本。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from config import EXPORT_DIR
from core.compare import PlatformStats
from core.database import Database
from core.models import Product


logger = logging.getLogger("viz")


# ---------------------------------------------------------------------------
# 中文字体配置
# ---------------------------------------------------------------------------
def _setup_chinese_font():
    """配置 matplotlib 中文字体"""
    import matplotlib
    matplotlib.use("Agg")  # 非交互后端
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    candidates = [
        "Microsoft YaHei", "PingFang SC", "Heiti SC",
        "Noto Sans CJK SC", "Source Han Sans SC",
        "WenQuanYi Zen Hei", "SimHei", "STHeiti", "Arial Unicode MS",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            logger.debug("使用中文字体: %s", name)
            return name
    # 没找到中文字体
    plt.rcParams["axes.unicode_minus"] = False
    logger.warning("未找到中文字体, 中文标签可能显示为方块")
    return None


_setup_chinese_font()


# ---------------------------------------------------------------------------
# 图表函数
# ---------------------------------------------------------------------------
def chart_platform_price_box(products: List[Product],
                             platform_names: Optional[dict] = None,
                             save_path: Optional[str] = None) -> str:
    """
    平台价格对比箱线图

    Args:
        products: 商品列表
        platform_names: 平台 -> 中文名
        save_path: 保存路径, 默认 EXPORT_DIR/box_<ts>.png

    Returns:
        保存文件路径
    """
    import matplotlib.pyplot as plt

    platform_names = platform_names or {}
    # 按平台分组价格
    groups = {}
    for p in products:
        if p.price <= 0:
            continue
        groups.setdefault(p.platform, []).append(p.price)

    if not groups:
        logger.warning("无有效价格数据, 跳过箱线图")
        return ""

    fig, ax = plt.subplots(figsize=(10, 6))
    labels = [platform_names.get(k, k) for k in groups.keys()]
    data = list(groups.values())
    # matplotlib 3.9+ 弃用 labels, 改用 tick_labels; 兼容旧版
    import matplotlib as _mpl
    _mpl_ver = tuple(int(x) for x in _mpl.__version__.split(".")[:2])
    box_kwargs = dict(patch_artist=True, showmeans=True,
                      meanprops={"marker": "D", "markerfacecolor": "red",
                                 "markeredgecolor": "red", "markersize": 6})
    if _mpl_ver >= (3, 9):
        bp = ax.boxplot(data, tick_labels=labels, **box_kwargs)
    else:
        bp = ax.boxplot(data, labels=labels, **box_kwargs)
    colors = ["#FF6B6B", "#4ECDC4", "#FFD93D", "#A8DADC", "#F4A261"]
    for patch, color in zip(bp["boxes"], colors[:len(bp["boxes"])]):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_title("各平台商品价格分布对比 (箱线图)", fontsize=14, fontweight="bold")
    ax.set_ylabel("价格 (元)", fontsize=12)
    ax.set_xlabel("平台", fontsize=12)
    ax.grid(True, alpha=0.3, axis="y")

    return _save_or_show(fig, save_path, "box")


def chart_price_distribution(products: List[Product],
                             bins: int = 20,
                             save_path: Optional[str] = None) -> str:
    """
    商品价格分布柱状图

    Args:
        products: 商品列表
        bins: 分桶数
        save_path: 保存路径

    Returns:
        保存文件路径
    """
    import matplotlib.pyplot as plt

    prices = [p.price for p in products if p.price > 0]
    if not prices:
        logger.warning("无有效价格数据, 跳过价格分布图")
        return ""

    fig, ax = plt.subplots(figsize=(10, 6))
    n, bins_arr, patches = ax.hist(prices, bins=bins, color="#4ECDC4",
                                    edgecolor="white", alpha=0.8)
    # 颜色渐变 (低价绿 -> 高价红)
    import matplotlib.cm as cm
    norm = plt.Normalize(min(prices), max(prices))
    for patch, left in zip(patches, bins_arr[:-1]):
        patch.set_facecolor(cm.RdYlGn_r(norm(left)))

    ax.set_title("商品价格分布 (柱状图)", fontsize=14, fontweight="bold")
    ax.set_xlabel("价格区间 (元)", fontsize=12)
    ax.set_ylabel("商品数量", fontsize=12)
    ax.grid(True, alpha=0.3, axis="y")

    # 标注统计信息
    avg = sum(prices) / len(prices)
    ax.axvline(avg, color="red", linestyle="--", linewidth=2, label=f"均价 ¥{avg:.2f}")
    ax.legend()

    return _save_or_show(fig, save_path, "distribution")


def chart_platform_avg(stats: List[PlatformStats],
                       save_path: Optional[str] = None) -> str:
    """
    平台均价对比柱状图

    Args:
        stats: 平台统计列表
        save_path: 保存路径

    Returns:
        保存文件路径
    """
    import matplotlib.pyplot as plt

    if not stats:
        logger.warning("无平台统计, 跳过均价图")
        return ""

    fig, ax = plt.subplots(figsize=(10, 6))
    names = [s.platform for s in stats]
    avg_prices = [s.avg_price for s in stats]
    min_prices = [s.min_price for s in stats]
    max_prices = [s.max_price for s in stats]

    import numpy as np
    x = np.arange(len(names))
    width = 0.25

    ax.bar(x - width, min_prices, width, label="最低价", color="#4ECDC4")
    ax.bar(x, avg_prices, width, label="均价", color="#FFD93D")
    ax.bar(x + width, max_prices, width, label="最高价", color="#FF6B6B")

    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_title("各平台价格区间对比 (最低/均价/最高)", fontsize=14, fontweight="bold")
    ax.set_ylabel("价格 (元)", fontsize=12)
    ax.set_xlabel("平台", fontsize=12)
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")

    # 数值标注
    for i, (mn, av, mx) in enumerate(zip(min_prices, avg_prices, max_prices)):
        ax.text(i - width, mn, f"¥{mn:.0f}", ha="center", va="bottom", fontsize=9)
        ax.text(i, av, f"¥{av:.0f}", ha="center", va="bottom", fontsize=9)
        ax.text(i + width, mx, f"¥{mx:.0f}", ha="center", va="bottom", fontsize=9)

    return _save_or_show(fig, save_path, "platform_avg")


def chart_price_trend(db: Database, url_hash: str,
                      title: str = "", days: int = 30,
                      save_path: Optional[str] = None) -> str:
    """
    单商品价格趋势折线图

    Args:
        db: 数据库实例
        url_hash: 商品 URL 哈希
        title: 图表标题 (商品标题)
        days: 天数
        save_path: 保存路径

    Returns:
        保存文件路径
    """
    import matplotlib.pyplot as plt

    trend = db.get_price_trend(url_hash, days)
    if len(trend) < 2:
        logger.info("历史数据点不足 (%d), 跳过趋势图", len(trend))
        return ""

    dates = [t[0] for t in trend]
    prices = [t[1] for t in trend]

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(dates, prices, marker="o", color="#FF6B6B",
            linewidth=2, markersize=8, markerfacecolor="white",
            markeredgecolor="#FF6B6B", markeredgewidth=2)

    # 填充
    ax.fill_between(range(len(prices)), prices, min(prices) - 1,
                    color="#FF6B6B", alpha=0.15)

    ax.set_title(f"价格趋势 - {title[:30]} (近{days}天)", fontsize=14, fontweight="bold")
    ax.set_ylabel("价格 (元)", fontsize=12)
    ax.set_xlabel("日期", fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(range(0, len(dates), max(1, len(dates) // 8)))
    ax.set_xticklabels(dates[::max(1, len(dates) // 8)], rotation=30, ha="right")

    # 极值标注
    min_idx = prices.index(min(prices))
    max_idx = prices.index(max(prices))
    ax.annotate(f"最低 ¥{prices[min_idx]:.2f}", xy=(min_idx, prices[min_idx]),
                xytext=(min_idx, prices[min_idx] - (max(prices) - min(prices)) * 0.3),
                arrowprops={"arrowstyle": "->", "color": "green"},
                fontsize=10, color="green", fontweight="bold")
    ax.annotate(f"最高 ¥{prices[max_idx]:.2f}", xy=(max_idx, prices[max_idx]),
                xytext=(max_idx, prices[max_idx] + (max(prices) - min(prices)) * 0.2),
                arrowprops={"arrowstyle": "->", "color": "red"},
                fontsize=10, color="red", fontweight="bold")

    plt.tight_layout()
    return _save_or_show(fig, save_path, f"trend_{url_hash}")


def _save_or_show(fig, save_path: Optional[str], prefix: str) -> str:
    """保存图表到文件, 返回路径"""
    import time as _t
    if save_path is None:
        save_path = str(EXPORT_DIR / f"{prefix}_{int(_t.time())}.png")
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120, bbox_inches="tight", facecolor="white")
    import matplotlib.pyplot as plt
    plt.close(fig)
    logger.info("图表已保存: %s", save_path)
    return save_path


__all__ = [
    "chart_platform_avg",
    "chart_platform_price_box",
    "chart_price_distribution",
    "chart_price_trend",
]
