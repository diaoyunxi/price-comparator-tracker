"""
示例数据生成器

读取 data/sample_products.json, 走完整清洗/对比/推荐流程, 输出 data/sample_result.json。
该文件作为 Web 应用初始化时展示的"对照示例"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SAMPLE_PRODUCTS, SAMPLE_RESULT, get_config
from core.compare import (
    build_compare_table,
    cheapest_vs_most_expensive,
    compute_recommendations,
    platform_stats,
)
from core.dedup import clean_products
from core.models import Product


def generate() -> dict:
    """生成示例结果"""
    raw = json.loads(SAMPLE_PRODUCTS.read_text(encoding="utf-8"))
    keyword = raw["keyword"]
    products = [Product.from_dict(p) for p in raw["products"]]

    cleaned, stats = clean_products(products)
    cfg = get_config()

    # 预计算价差信息，避免重复调用
    gap_info = cheapest_vs_most_expensive(cleaned)

    return {
        "keyword": keyword,
        "platforms": raw["platforms"],
        "generated_at": raw["generated_at"],
        "_comment": "由 tools/gen_sample.py 从 sample_products.json 自动生成, 作为 Web 初始化展示示例",
        "clean_stats": stats,
        "products": [p.to_dict() for p in cleaned],
        "platform_stats": [
            {
                "platform": s.platform, "count": s.count,
                "avg_price": s.avg_price, "min_price": s.min_price,
                "max_price": s.max_price, "median_price": s.median_price,
                "avg_sales": s.avg_sales, "avg_rating": s.avg_rating,
            } for s in platform_stats(cleaned, cfg.platforms)
        ],
        "recommendations": [
            {
                "rank": r.rank, "score": r.score, "reason": r.reason,
                "product": r.product.to_dict(),
            } for r in compute_recommendations(cleaned, cfg.recommend_top_n)
        ],
        "compare_table": build_compare_table(cleaned),
        "cheapest": gap_info["cheapest"].to_dict() if gap_info["cheapest"] else None,
        "most_expensive": gap_info["most_expensive"].to_dict() if gap_info["most_expensive"] else None,
        "price_gap": gap_info["price_gap"],
        "price_gap_ratio": gap_info["price_gap_ratio"],
        "total": len(cleaned),
    }


def main() -> int:
    result = generate()
    SAMPLE_RESULT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已生成示例结果: {SAMPLE_RESULT}")
    print(f"  关键词: {result['keyword']}")
    print(f"  商品数: {result['total']}")
    print(f"  推荐数: {len(result['recommendations'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
