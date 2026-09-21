"""
安装与初始化脚本

功能:
1. 检查 Python 版本
2. 安装 pip 依赖
3. 创建必要目录
4. 生成示例数据 (data/sample_result.json)
5. 检查更新 (调用 updater)
6. 输出运行指引

用法:
    python install.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# 让本脚本可直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    PROJECT_ROOT, DATA_DIR, RUNTIME_DIR, EXPORT_DIR, LOG_DIR,
    DB_PATH, read_version,
)


REQUIRED_PY = (3, 8)


def check_python_version() -> bool:
    """检查 Python 版本"""
    v = sys.version_info
    if v[:2] < REQUIRED_PY:
        print(f"[FAIL] 需要 Python {REQUIRED_PY[0]}.{REQUIRED_PY[1]}+, 当前 {v.major}.{v.minor}")
        return False
    print(f"[OK] Python {v.major}.{v.minor}.{v.micro}")
    return True


def install_dependencies() -> bool:
    """安装 pip 依赖"""
    req = PROJECT_ROOT / "requirements.txt"
    if not req.exists():
        print("[FAIL] requirements.txt 不存在")
        return False
    print(f"\n[INSTALL] 安装依赖 (pip install -r requirements.txt)...")
    # 选择性安装: playwright 较重, 单独提示
    rc = subprocess.call(
        [sys.executable, "-m", "pip", "install", "-r", str(req),
         "--disable-pip-version-check", "--quiet"],
    )
    if rc != 0:
        print("[WARN] 依赖安装可能不完整, 部分功能可能不可用")
        return False
    print("[OK] 依赖安装完成")
    return True


def ensure_dirs() -> None:
    """创建必要目录"""
    for d in (DATA_DIR, RUNTIME_DIR, EXPORT_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
    print(f"[OK] 目录就绪: {RUNTIME_DIR.relative_to(PROJECT_ROOT)}")


def generate_sample() -> None:
    """生成示例数据"""
    gen = PROJECT_ROOT / "tools" / "gen_sample.py"
    if not gen.exists():
        print("[WARN] tools/gen_sample.py 不存在, 跳过示例数据生成")
        return
    rc = subprocess.call([sys.executable, str(gen)], cwd=str(PROJECT_ROOT))
    if rc == 0:
        print("[OK] 示例数据已生成")
    else:
        print("[WARN] 示例数据生成失败")


def check_updates() -> None:
    """检查更新"""
    print("\n[CHECK] 检查更新...")
    try:
        from updater import check_for_updates
        has_update, release = check_for_updates(silent=True)
        if has_update and release:
            print(f"[INFO] 发现新版本: {release.get('tag_name')} (当前 v{read_version()})")
            print(f"       详情: {release.get('html_url')}")
        else:
            print(f"[OK] 已是最新版本 v{read_version()}")
    except Exception as e:
        print(f"[WARN] 更新检查失败: {e}")


def verify_imports() -> bool:
    """验证关键模块可导入"""
    print("\n[VERIFY] 验证模块导入...")
    try:
        from core.models import Product
        from core.database import Database
        from core.dedup import clean_products
        from core.compare import compute_recommendations
        from core.runner import run_crawl
        from scrapers import get_scraper
        print("[OK] 核心模块导入成功")
    except Exception as e:
        print(f"[FAIL] 核心模块导入失败: {e}")
        return False
    try:
        import fastapi, uvicorn, requests, bs4
        print("[OK] Web/爬虫依赖导入成功")
    except Exception as e:
        print(f"[WARN] 部分依赖缺失: {e}")
    try:
        import matplotlib
        print("[OK] matplotlib 可用 (CLI 图表功能就绪)")
    except Exception:
        print("[WARN] matplotlib 未安装, CLI 图表功能不可用 (Web 不受影响)")
    try:
        import rich
        print("[OK] rich 可用 (CLI 表格美化就绪)")
    except Exception:
        print("[INFO] rich 未安装, CLI 将使用简化表格")
    return True


def print_usage() -> None:
    """打印使用指引"""
    print(f"""
{'=' * 60}
  电商商品价格采集与对比工具 v{read_version()} - 安装完成
{'=' * 60}

  命令行使用:
    # 快速演示 (Mock 数据)
    python cli.py demo

    # 标准采集 (真实爬虫 + Mock 回退)
    python cli.py search 蓝牙耳机

    # 指定平台与数量, 导出 CSV + 图表
    python cli.py search 机械键盘 --platforms jd,pdd --limit 20 --export csv --chart

    # 查看历史记录
    python cli.py history

  Web 使用:
    # 启动 FastAPI 服务 (默认 http://localhost:8765)
    python main.py

    # 或使用 uvicorn
    uvicorn main:app --host 0.0.0.0 --port 8765 --reload

  数据库: {DB_PATH.relative_to(PROJECT_ROOT)}
  导出目录: {EXPORT_DIR.relative_to(PROJECT_ROOT)}

  反爬配置: 编辑 config.local.yaml (可选)
  代理池:   创建 proxy_pool.txt (每行一个 http://ip:port)
  Cookie:   在 cookies/<platform>.txt 放置登录 Cookie

  文档: README.md
  API:  http://localhost:8765/docs
{'=' * 60}
""")


def main() -> int:
    print(f"\n  电商商品价格采集与对比工具 v{read_version()} 安装程序\n")
    if not check_python_version():
        return 1
    ensure_dirs()
    ok = install_dependencies()
    verify_imports()
    generate_sample()
    check_updates()
    print_usage()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
