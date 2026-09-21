"""
FastAPI Web 应用入口

启动方式:
    python main.py
    # 或
    uvicorn main:app --host 0.0.0.0 --port 8765 --reload

API:
    GET  /                  首页 (含输入框 + 示例展示)
    GET  /api/sample        获取初始示例数据
    POST /api/crawl         启动采集任务 (异步, 返回 task_id)
    GET  /api/task/{id}     查询任务状态与结果
    GET  /api/history       历史关键词列表
    GET  /api/trend          某商品价格趋势 (?url_hash=...)
    GET  /api/keywords       关键词列表
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config import PROJECT_ROOT, SAMPLE_PRODUCTS, SAMPLE_RESULT, get_config, read_version
from core.database import Database
from core.runner import run_crawl


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("web")


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------
app = FastAPI(
    title="电商商品价格自动化采集与对比工具",
    version=read_version(),
    description="按关键词采集京东/淘宝/拼多多商品, 清洗去重, 性价比推荐, 趋势图",
)

TEMPLATES_DIR = PROJECT_ROOT / "web" / "templates"
STATIC_DIR = PROJECT_ROOT / "web" / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

db = Database()


# ---------------------------------------------------------------------------
# 任务管理 (内存中, 进程级)
# ---------------------------------------------------------------------------
class TaskStore:
    """简单内存任务存储 (生产环境应换 Redis)"""

    def __init__(self) -> None:
        self.tasks: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        # 保存后台任务引用，避免 "Task exception was never retrieved" 警告
        self._bg_tasks: Dict[str, asyncio.Task] = {}

    async def create(self, keyword: str, platforms: list, limit: int,
                     use_mock: bool) -> str:
        task_id = uuid.uuid4().hex[:12]
        self.tasks[task_id] = {
            "task_id": task_id,
            "keyword": keyword,
            "platforms": platforms,
            "limit": limit,
            "use_mock": use_mock,
            "status": "pending",  # pending/running/success/failed
            "progress": 0,
            "started_at": time.time(),
            "finished_at": None,
            "error": None,
            "result": None,
        }
        return task_id

    async def update(self, task_id: str, **fields) -> None:
        if task_id in self.tasks:
            self.tasks[task_id].update(fields)

    def get(self, task_id: str) -> Optional[dict]:
        return self.tasks.get(task_id)


tasks_store = TaskStore()


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------
class CrawlRequest(BaseModel):
    keyword: str
    platforms: list[str] = ["jd", "taobao", "pdd"]
    limit: int = 30
    use_mock: bool = False


# ---------------------------------------------------------------------------
# 异步任务执行
# ---------------------------------------------------------------------------
async def _run_crawl_task(task_id: str, req: CrawlRequest) -> None:
    """后台执行采集任务"""
    await tasks_store.update(task_id, status="running", progress=10)
    try:
        # 在线程池中执行 (避免阻塞事件循环)
        # 使用 get_running_loop 获取当前运行的事件循环 (get_event_loop 在 3.10+ 已弃用)
        loop = asyncio.get_running_loop()
        # 分阶段更新进度
        await tasks_store.update(task_id, progress=30)
        # 为每个任务创建独立的 Database 实例, 避免多线程共享连接导致锁冲突
        task_db = Database()
        result = await loop.run_in_executor(
            None,
            lambda: run_crawl(
                keyword=req.keyword,
                platforms=req.platforms,
                limit_per_platform=req.limit,
                use_mock=req.use_mock,
                db=task_db,
                parallel=True,
            ),
        )
        await tasks_store.update(task_id, progress=90)
        # 序列化结果
        result_dict = result.to_dict()
        # 处理 Product / Recommendation 嵌套
        result_dict["products"] = [p.to_dict() if hasattr(p, "to_dict") else p
                                    for p in result.products]
        result_dict["recommendations"] = [
            {**{"rank": r.rank, "score": r.score, "reason": r.reason},
             **{"product": r.product.to_dict()}}
            for r in result.recommendations
        ]
        result_dict["platform_stats"] = [
            {
                "platform": s.platform, "count": s.count,
                "avg_price": s.avg_price, "min_price": s.min_price,
                "max_price": s.max_price, "median_price": s.median_price,
                "avg_sales": s.avg_sales, "avg_rating": s.avg_rating,
            } for s in result.platform_stats
        ]
        result_dict["cheapest"] = result.cheapest.to_dict() if result.cheapest else None
        result_dict["most_expensive"] = (result.most_expensive.to_dict()
                                          if result.most_expensive else None)

        await tasks_store.update(
            task_id,
            status="success", progress=100,
            finished_at=time.time(),
            result=result_dict,
        )
        logger.info("任务完成: %s keyword=%s", task_id, req.keyword)
    except Exception as e:
        logger.exception("任务失败: %s", task_id)
        await tasks_store.update(
            task_id,
            status="failed", finished_at=time.time(),
            error=str(e),
        )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页"""
    # 兼容新旧 Starlette API:
    # 旧版: TemplateResponse(name, context)  (context 含 request)
    # 新版: TemplateResponse(request, name, context)
    try:
        # 优先新版 API
        return templates.TemplateResponse(
            request, "index.html",
            {"version": read_version(), "platforms": get_config().platforms},
        )
    except TypeError:
        # 退化旧版 API
        return templates.TemplateResponse("index.html", {
            "request": request,
            "version": read_version(),
            "platforms": get_config().platforms,
        })


@app.get("/api/sample")
async def api_sample():
    """
    返回初始示例数据 (sample_products + sample_result)

    若 sample_result.json 不存在, 自动生成。
    """
    if not SAMPLE_RESULT.exists():
        try:
            import asyncio
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(PROJECT_ROOT / "tools" / "gen_sample.py"),
                cwd=str(PROJECT_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                raise Exception(f"Process failed with code {proc.returncode}")
        except Exception as e:
            logger.warning("自动生成示例失败: %s", e)
            return JSONResponse({"error": f"sample_not_ready: {e}"}, status_code=500)

    result = json.loads(SAMPLE_RESULT.read_text(encoding="utf-8"))
    raw = json.loads(SAMPLE_PRODUCTS.read_text(encoding="utf-8"))
    return {
        "raw": {
            "keyword": raw["keyword"],
            "platforms": raw["platforms"],
            "products": raw["products"],
        },
        "result": result,
    }


@app.post("/api/crawl")
async def api_crawl(req: CrawlRequest):
    """启动采集任务, 返回 task_id"""
    if not req.keyword or not req.keyword.strip():
        raise HTTPException(400, "关键词不能为空")
    keyword = req.keyword.strip()
    # 校验关键词长度 (1-100 字符)
    if len(keyword) < 1 or len(keyword) > 100:
        raise HTTPException(400, "关键词长度必须在 1-100 个字符之间")
    # 校验关键词内容 (仅允许中文、英文、数字、空格及常见标点)
    if not re.match(r'^[\w\s\u4e00-\u9fff\-_.+/]+$', keyword):
        raise HTTPException(400, "关键词包含非法字符，仅允许中文、英文、数字及常见符号")
    cfg = get_config()
    # 验证平台
    valid_platforms = set(cfg.platforms.keys())
    req.platforms = [p for p in req.platforms if p in valid_platforms]
    if not req.platforms:
        req.platforms = list(valid_platforms)
    if req.limit < 1 or req.limit > 100:
        raise HTTPException(400, "limit 必须在 1-100 之间")

    # 任务并发限制
    running = sum(1 for t in tasks_store.tasks.values() if t["status"] == "running")
    if running >= cfg.web.max_concurrent_tasks:
        raise HTTPException(429, f"已有 {running} 个任务在跑, 稍后再试")

    task_id = await tasks_store.create(
        keyword=keyword,
        platforms=req.platforms,
        limit=req.limit,
        use_mock=req.use_mock,
    )
    task = asyncio.create_task(_run_crawl_task(task_id, req))
    tasks_store._bg_tasks[task_id] = task
    task.add_done_callback(lambda t, tid=task_id: tasks_store._bg_tasks.pop(tid, None))
    return {"task_id": task_id, "status": "pending"}


@app.get("/api/task/{task_id}")
async def api_task(task_id: str):
    """查询任务状态"""
    task = tasks_store.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@app.get("/api/history")
async def api_history(limit: int = 20):
    """历史关键词列表"""
    return {
        "total_records": db.count_total(),
        "keywords": [{"keyword": k, "last_fetched": t}
                     for k, t in db.list_keywords(limit)],
    }


@app.get("/api/trend")
async def api_trend(url_hash: str, days: int = 30):
    """某商品价格趋势"""
    # 参数长度校验, 防止超长输入造成异常
    if not url_hash or len(url_hash) > 128:
        raise HTTPException(400, "url_hash 长度必须在 1-128 个字符之间")
    if days < 1 or days > 365:
        raise HTTPException(400, "days 必须在 1-365 之间")
    trend = db.get_price_trend(url_hash, days)
    return {
        "url_hash": url_hash,
        "days": days,
        "points": [{"date": d, "price": p} for d, p in trend],
    }


@app.get("/api/trend/keyword")
async def api_trend_keyword(keyword: str, days: int = 30):
    """关键词下所有商品价格趋势"""
    # 参数长度校验, 防止超长输入造成异常
    if not keyword or not keyword.strip() or len(keyword) > 100:
        raise HTTPException(400, "keyword 长度必须在 1-100 个字符之间")
    if days < 1 or days > 365:
        raise HTTPException(400, "days 必须在 1-365 之间")
    trends = db.get_trend_for_keyword(keyword, days)
    return {
        "keyword": keyword,
        "days": days,
        "trends": [
            {"url_hash": h, "points": [{"date": d, "price": p} for d, p in pts]}
            for h, pts in trends.items()
        ],
    }


@app.get("/api/health")
async def api_health():
    """健康检查"""
    return {"status": "ok", "version": read_version(), "db_records": db.count_total()}


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------
def main() -> int:
    """启动 uvicorn 服务"""
    import uvicorn
    cfg = get_config().web
    print(f"\n  电商商品价格采集与对比工具 v{read_version()}")
    print(f"  访问地址: http://localhost:{cfg.port}")
    print(f"  API 文档: http://localhost:{cfg.port}/docs\n")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
