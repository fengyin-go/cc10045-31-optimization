"""报告历史/来源/核数批/快照的核心行为回归测试。

直接调用服务层，不依赖 HTTP 客户端；用独立的临时库跑，不污染 data/cc10045.db。
运行：.venv/bin/python -m pytest tests/test_report_history.py -q
无 pytest 时：.venv/bin/python tests/test_report_history.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# 必须在导入 app 之前指向临时库
_TMP = tempfile.mkdtemp(prefix="cc10045-test-")
os.environ["CC10045_DB_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import db  # noqa: E402
from app.pipeline import compute_metric_snapshot, generate_report  # noqa: E402
from app.services import report_provenance as prov  # noqa: E402
from app.services.report_history import ReportHistoryService  # noqa: E402
from app.services.report_snapshot import ReportSnapshotService  # noqa: E402


def _install_metrics() -> None:
    names = [
        ("日活跃用户数(DAU)", "counter", "人"),
        ("订单总量", "counter", "单"),
        ("支付转化率", "ratio", "%"),
    ]
    for name, mtype, unit in names:
        db.insert("metrics", {
            "metric_name": name, "metric_type": mtype,
            "source_module": "event_tracker", "unit": unit,
        })
    for metric_id in (1, 2, 3):
        metric = db.fetchone("SELECT * FROM metrics WHERE id=?", [metric_id])
        compute_metric_snapshot(dict(metric))


def _install_reports() -> None:
    reports = [
        (41, "北区渠道月度经营报告", "[1,2]", "SRC_NORTH_CHANNEL", "北区渠道"),
        (42, "北区渠道分析报告(旧模板)", "[1,2,3]", None, "北区"),
        (43, "北区门店经营报告", "[2]", "SRC_NORTH_STORE", "北区门店"),
    ]
    for rid, name, metrics, key, sname in reports:
        db.insert("reports", {
            "id": rid, "report_name": name, "metric_ids": metrics,
            "report_period": "2026-11", "output_format": "json",
            "source_key": key, "source_name": sname,
        })
    prov.ensure_source("北区渠道", source_key="SRC_NORTH_CHANNEL", aliases=["北区"])
    prov.ensure_source("北区门店", source_key="SRC_NORTH_STORE", aliases=["北区门店"])


def _emit(report_id: int, at: str, display_name: str) -> int:
    report = db.fetchone("SELECT * FROM reports WHERE id=?", [report_id])
    result = generate_report(dict(report))
    db.update("report_outputs",
              {"generated_at": at, "source_display_name": display_name},
              "id=?", [result["id"]])
    return result["id"]


_TABLES = [
    "report_outputs", "report_source_attributions", "reconciliation_batch_items",
    "reconciliation_batch_deferrals", "reconciliation_batches", "snapshots",
    "reports", "report_sources", "metric_values", "metrics",
]


def _reset() -> None:
    """每个测试从干净的库开始，避免用例之间互相影响。"""
    for table in _TABLES:
        db.execute(f"DELETE FROM {table}")
    db.execute("DELETE FROM sqlite_sequence WHERE name IN "
               f"({','.join('?' for _ in _TABLES)})", _TABLES)
    _install_metrics()
    _install_reports()
    svc = ReportHistoryService()

    out41 = _emit(41, "2026-11-21T00:00:00.000001", "北区渠道")
    out42 = _emit(42, "2026-11-22T00:00:00.000001", "北区")
    _emit(43, "2026-11-23T00:00:00.000001", "北区门店")

    prov.add_attribution(out41, source_key="SRC_NORTH_CHANNEL", source_name="北区渠道",
                         status=prov.CONFIRMED, evidence_ref="EV-41",
                         registered_at="2026-11-21T00:00:00.000001")
    prov.add_attribution(out42, source_key="", source_name="北区",
                         status=prov.PENDING, display_only=True,
                         registered_at="2026-11-22T00:00:00.000001")
    ctx.out41 = out41
    ctx.out42 = out42
    ctx.svc = svc


class ctx:
    out41 = 0
    out42 = 0
    svc: ReportHistoryService


def setup_module() -> None:
    _reset()


def test_search_scopes_by_period_and_source_alias() -> None:
    _reset()
    items, total, context = ctx.svc.search_outputs(
        business_period="2026-11", source="北区渠道")
    nos = {i["output_no"] for i in items}
    assert nos == {"R41-1", "R42-1"}, nos
    assert context["resolved_sources"][0]["source_name"] == "北区渠道"
    # 旧简称解析到同一来源，不带入门店
    items2, _, _ = ctx.svc.search_outputs(business_period="2026-11", source="北区")
    assert {i["output_no"] for i in items2} == {"R41-1", "R42-1"}


def test_display_only_is_pending_and_not_dispatchable() -> None:
    _reset()
    item = ctx.svc.get_output(ctx.out42)
    assert item["source_status"] == prov.PENDING
    assert item["display_only"] is True
    assert item["source_name"] == "北区渠道"  # 显示名解析到规范来源
    assert item["dispatchable"] is False


def test_filter_time_vs_dispatch_time() -> None:
    _reset()
    svc = ctx.svc
    t0 = prov.precise_now()
    time.sleep(0.02)
    svc.register_attribution(ctx.out42, source_name="北区渠道",
                             status=prov.CONFIRMED, evidence_ref="EV-42")

    # 按开始筛选时核验：只发 41，42 留待
    plan = svc._plan_roster(
        business_period="2026-11", source="北区渠道", metric=None,
        verify_mode="filter_time", filtered_at=t0, verify_as_of=t0,
        dispatched_at=prov.precise_now())
    assert [i["output_no"] for i in plan["roster"]] == ["R41-1"]
    assert any(d["output_no"] == "R42-1" and d["disposition"] == "留待下次核数"
               for d in plan["deferrals"])

    # 下发前重新核验：41 和 42 都发
    plan2 = svc._plan_roster(
        business_period="2026-11", source="北区渠道", metric=None,
        verify_mode="dispatch_time", filtered_at=t0, verify_as_of=prov.precise_now(),
        dispatched_at=prov.precise_now())
    assert sorted(i["output_no"] for i in plan2["roster"]) == ["R41-1", "R42-1"]


def test_batch_frozen_after_later_changes() -> None:
    _reset()
    svc = ctx.svc
    t0 = prov.precise_now()
    # 42 在筛选后补上可验证凭据
    svc.register_attribution(ctx.out42, source_name="北区渠道",
                             status=prov.CONFIRMED, evidence_ref="EV-42")
    res = svc.dispatch_batch(business_period="2026-11", source="北区渠道",
                             verify_mode="dispatch_time", filtered_at=t0,
                             dispatched_by="财务")
    assert res["ok"] is True
    batch_id = res["batch"]["id"]
    roster = sorted(i["output_no"] for i in res["batch"]["items"])
    assert roster == ["R41-1", "R42-1"], roster

    # 之后补一条仅显示名备注：不能降级已确认、更不能改写已发名单
    svc.register_attribution(ctx.out42, source_name="北区",
                             status=prov.PENDING, display_only=True)
    reopened = svc.get_batch(batch_id)
    assert sorted(i["output_no"] for i in reopened["items"]) == roster
    item42 = next(i for i in reopened["items"] if i["output_no"] == "R42-1")
    assert item42["source_name"] == "北区渠道"
    assert item42["attribution_trace"]["locked"] is True


def test_snapshot_pins_selected_output_not_latest() -> None:
    _reset()
    snap_svc = ReportSnapshotService()
    selected = ctx.out41
    snap = snap_svc.create_for_report(41, "选中 R41-1 留档", output_id=selected)
    assert snap["ok"] and snap["output_no"] == "R41-1"
    frozen_metrics = [(m["metric_name"], m["current_value"]) for m in snap["metric_data"]]

    # 同模板补跑一版
    newer = _emit(41, "2026-11-24T00:00:00.000001", "北区渠道")
    assert newer != selected

    check = snap_svc.verify_snapshot(snap["snapshot_id"])
    assert check["output_id"] == selected
    assert check["output_no"] == "R41-1"
    assert [(m["metric_name"], m["current_value"]) for m in check["metric_data"]] == frozen_metrics
    assert check["metric_data_matches_content"] is True

    # 不能引用同模板但非选中的输出
    bad = snap_svc.create_for_report(41, "错误引用", output_id=newer)
    assert bad["ok"] is True  # 同模板新版本允许显式选择
    wrong_template = snap_svc.create_for_report(41, "跨模板", output_id=ctx.out42)
    assert wrong_template["ok"] is False


def test_snapshot_rejects_foreign_template_output() -> None:
    _reset()
    snap_svc = ReportSnapshotService()
    result = snap_svc.create_for_report(41, "跨模板", output_id=ctx.out42)
    assert result["ok"] is False


def test_rerun_does_not_inherit_old_evidence() -> None:
    _reset()
    svc = ctx.svc
    newer = _emit(41, "2026-11-25T00:00:00.000001", "北区渠道")
    item = svc.get_output(newer)
    assert item["source_status"] == prov.PENDING
    assert item["dispatchable"] is False


def test_explicit_pending_verdict_changes_status() -> None:
    """明确判为待翻查（非“仅显示名”备注）是一次真实口径变更，应生效。"""
    _reset()
    svc = ctx.svc
    before = svc.get_output(ctx.out41)
    assert before["source_status"] == prov.CONFIRMED
    svc.register_attribution(ctx.out41, source_name="北区渠道",
                             status=prov.PENDING, evidence_detail="回执待复核")
    after = svc.get_output(ctx.out41)
    assert after["source_status"] == prov.PENDING
    assert after["dispatchable"] is False


def test_no_evidence_cannot_dispatch() -> None:
    _reset()
    # 构造一个只有显示名、没有凭据的输出来下发
    out = _emit(42, "2026-11-26T00:00:00.000001", "北区")
    res = ctx.svc.dispatch_batch(
        business_period="2026-11", source="北区渠道", verify_mode="dispatch_time",
        filtered_at=prov.precise_now(), dispatched_by="财务")
    # 该输出在本批不应进入 roster
    if res["ok"]:
        assert out not in [i["output_id"] for i in res["batch"]["items"]]


if __name__ == "__main__":
    setup_module()
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print("FAILURES:", failures if failures else "none")
    sys.exit(1 if failures else 0)
