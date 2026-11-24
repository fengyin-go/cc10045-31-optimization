"""业务路由汇总：资源路由 + 管道路由 + 报告历史路由。"""
from __future__ import annotations

from app.routers import report_history, resource
from app.routers import pipeline

ROUTERS = [resource]
EXTRA_ROUTERS = [report_history]
PIPELINE_ROUTER = pipeline.router