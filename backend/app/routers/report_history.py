"""报告历史、来源凭据、快照留档与核数批次接口。

这些接口挂在 `/api/report-history` 下，和通用资源路由分开，
避免与 `/api/{module}` 的模块分派冲突。

路由顺序很重要：所有静态段（/sources、/batches、/snapshots）必须声明在
`/{output_id}` 之前，否则 "batches" 会被当成整数路径参数而返回 422。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services import report_provenance as prov
from app.services.report_history import report_history_service
from app.services.report_snapshot import ReportSnapshotService

router = APIRouter(prefix="/api/report-history", tags=["报告历史与核数"])
snapshot_service = ReportSnapshotService()


class AttributionPayload(BaseModel):
    source_name: str = ""
    source_key: str | None = None
    status: str = prov.CONFIRMED
    evidence_ref: str | None = None
    evidence_detail: str | None = None
    display_only: bool = False
    registered_by: str = ""
    registered_at: str | None = None


class DispatchPayload(BaseModel):
    business_period: str
    source: str | None = None
    metric: str | None = None
    verify_mode: str = "filter_time"
    filtered_at: str | None = None
    dispatched_by: str = ""
    note: str = ""
    dry_run: bool = False
    dispatched_at: str | None = None


class SnapshotPayload(BaseModel):
    report_id: int
    output_id: int
    snapshot_name: str = ""
    as_of: str | None = None


# ====================================================================
# 来源
# ====================================================================

@router.get("/sources")
def list_sources() -> dict[str, Any]:
    """列出取数来源及其历史旧简称。"""
    sources = prov.list_sources()
    return {"items": sources, "total": len(sources)}


@router.get("/sources/resolve")
def resolve_source(q: str = Query(default="")) -> dict[str, Any]:
    """把检索词（规范名或旧简称）解析为来源。"""
    matched = prov.resolve_sources(q)
    return {"query": q, "resolved": matched, "ambiguous": len(matched) > 1}


# ====================================================================
# 核数批次
# ====================================================================

@router.post("/batches")
def dispatch_batch(payload: DispatchPayload) -> dict[str, Any]:
    """按本次查验结果下发核数批；名单在下发时冻结。dry_run=true 只试算不落库。"""
    return report_history_service.dispatch_batch(
        business_period=payload.business_period,
        source=payload.source,
        metric=payload.metric,
        verify_mode=payload.verify_mode,
        filtered_at=payload.filtered_at,
        dispatched_by=payload.dispatched_by,
        note=payload.note,
        dry_run=payload.dry_run,
        dispatched_at=payload.dispatched_at,
    )


@router.get("/batches")
def list_batches() -> dict[str, Any]:
    items = report_history_service.list_batches()
    return {"items": items, "total": len(items)}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int) -> dict[str, Any]:
    """重新打开已发出的核数批，仍能拿到当次名单（不受后续补登影响）。"""
    batch = report_history_service.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"核数批 {batch_id} 不存在")
    return batch


# ====================================================================
# 快照留档
# ====================================================================

@router.post("/snapshots")
def create_snapshot(payload: SnapshotPayload) -> dict[str, Any]:
    """按选中的报告输出留档：固化输出编号、当时来源及该版指标数据。"""
    name = payload.snapshot_name.strip() or f"报告{payload.report_id}输出{payload.output_id}快照"
    return snapshot_service.create_for_report(
        payload.report_id, name,
        output_id=payload.output_id, as_of=payload.as_of,
    )


@router.get("/snapshots")
def list_snapshots(report_id: int | None = Query(default=None)) -> dict[str, Any]:
    if report_id is not None:
        items = snapshot_service.report_snapshots(report_id)
    else:
        items = snapshot_service.report_snapshots_all()
    return {"items": items, "total": len(items)}


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: int) -> dict[str, Any]:
    snapshot = snapshot_service.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"快照 {snapshot_id} 不存在")
    return snapshot


@router.get("/snapshots/{snapshot_id}/verify")
def verify_snapshot(snapshot_id: int) -> dict[str, Any]:
    """完全从快照自身核对，不回读最新输出。"""
    result = snapshot_service.verify_snapshot(snapshot_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"快照 {snapshot_id} 不存在")
    return result


# ====================================================================
# 输出检索与来源凭据（动态段，必须放最后）
# ====================================================================

@router.get("")
def search_outputs(
    business_period: str | None = Query(default=None),
    source: str | None = Query(default=None),
    metric: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    as_of: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """按业务期间、来源、指标检索实际生成的报告输出。"""
    items, total, context = report_history_service.search_outputs(
        business_period=business_period, source=source, metric=metric,
        keyword=keyword, as_of=as_of, page=page, size=size,
    )
    return {"items": items, "total": total, "page": page, "size": size, "context": context}


@router.get("/{output_id}")
def get_output(output_id: int, as_of: str | None = Query(default=None)) -> dict[str, Any]:
    view = report_history_service.get_output(output_id, as_of=as_of)
    if view is None:
        raise HTTPException(status_code=404, detail=f"报告输出 {output_id} 不存在")
    return view


@router.get("/{output_id}/attributions")
def attribution_history(output_id: int) -> dict[str, Any]:
    """逐条核对一条输出采用过哪些来源凭据。"""
    output = report_history_service.get_output(output_id)
    if output is None:
        raise HTTPException(status_code=404, detail=f"报告输出 {output_id} 不存在")
    history = report_history_service.attribution_history(output_id)
    return {"output_id": output_id, "output_no": output["output_no"],
            "items": history, "total": len(history)}


@router.post("/{output_id}/attributions")
def register_attribution(output_id: int, payload: AttributionPayload) -> dict[str, Any]:
    """登记一条来源凭据；同一条输出可多次补登，按登记时点还原。"""
    return report_history_service.register_attribution(
        output_id,
        source_name=payload.source_name,
        source_key=payload.source_key,
        status=payload.status,
        evidence_ref=payload.evidence_ref,
        evidence_detail=payload.evidence_detail,
        display_only=payload.display_only,
        registered_by=payload.registered_by,
        registered_at=payload.registered_at,
    )
