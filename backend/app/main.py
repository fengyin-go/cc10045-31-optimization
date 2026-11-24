"""实时数据分析与可视化应用平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8019
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import db
from app.pipeline import seed_real_data
from app.routers import EXTRA_ROUTERS, PIPELINE_ROUTER, ROUTERS
from app.seed_report_history import seed_report_history
from app.store import store

app = FastAPI(title="实时数据分析与可视化应用平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_seed() -> None:
    """应用启动时初始化种子数据。"""
    try:
        existing = db.count("metrics")
        if existing == 0:
            counts = seed_real_data()
            print(f"[seed] 数据集初始化完成: {counts}")
        else:
            print(f"[seed] 数据集已存在，跳过初始化 (metrics={existing})")
        report_counts = seed_report_history()
        print(f"[seed] 报告历史场景: {report_counts}")
    except Exception as e:
        print(f"[seed] 初始化失败: {e}")


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"ok": True, "app": settings.app_name, "tables": len(db.table_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    return store.overview()


# 报告历史/来源/核数/快照路由：静态前缀，需在 /api/{module} 之前注册
for extra in EXTRA_ROUTERS:
    app.include_router(extra.router)

# 管道路由：数据分析核心入口
app.include_router(PIPELINE_ROUTER)

# 资源路由含 /api/{module}，必须放在 health / overview 之后注册
for module in ROUTERS:
    app.include_router(module.router)