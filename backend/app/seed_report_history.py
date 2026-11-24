"""报告历史场景种子：北区渠道 / 北区门店、同一业务期间的多次生成输出。

只在 reports 表为空时写入，保证重复启动不会覆盖用户已经操作过的数据。
场景对应：
- 报告 41：北区渠道月度报告，输出已有可验证凭据（已确认）；
- 报告 42：同一期间的另一份渠道报告，存量正文只有旧简称“北区”，待翻查；
- 报告 43：后跑的北区门店报告，与 41/42 属于不同来源，检索“北区渠道”时不应被带入。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import db
from app.pipeline import generate_report
from app.services import report_provenance as prov


def _ts(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%S.%f")


def seed_report_history() -> dict[str, Any]:
    if db.count("reports") > 0:
        return {"skipped": True, "reports": db.count("reports")}

    # ---- 来源登记：规范名 + 历史旧简称 ----
    prov.ensure_source("北区渠道", source_key="SRC_NORTH_CHANNEL",
                       source_type="渠道", aliases=["北区", "北区渠道事业部"])
    prov.ensure_source("北区门店", source_key="SRC_NORTH_STORE",
                       source_type="门店", aliases=["北区门店", "北区直营门店"])
    prov.ensure_source("东区渠道", source_key="SRC_EAST_CHANNEL",
                       source_type="渠道", aliases=["东区"])

    # ---- 指标数据：确保报告输出有本版指标值 ----
    from app.pipeline import compute_metric_snapshot
    for metric_id in (1, 2, 3):
        metric = db.fetchone("SELECT * FROM metrics WHERE id=?", [metric_id])
        if metric:
            compute_metric_snapshot(dict(metric))

    period = "2026-11"
    t_41 = _ts(timedelta(days=-3))
    t_42 = _ts(timedelta(days=-2))
    t_43 = _ts(timedelta(hours=-2))
    t_old = _ts(timedelta(days=-40))

    reports = [
        {"id": 41, "report_name": "北区渠道月度经营报告", "metric_ids": json.dumps([1, 2]),
         "report_period": period, "output_format": "json", "auto_send": 1, "status": "已发布",
         "source_key": "SRC_NORTH_CHANNEL", "source_name": "北区渠道"},
        {"id": 42, "report_name": "北区渠道分析报告(旧模板)", "metric_ids": json.dumps([1, 2, 3]),
         "report_period": period, "output_format": "json", "auto_send": 0, "status": "已发布",
         "source_key": None, "source_name": "北区"},
        {"id": 43, "report_name": "北区门店经营报告", "metric_ids": json.dumps([2]),
         "report_period": period, "output_format": "json", "auto_send": 0, "status": "已发布",
         "source_key": "SRC_NORTH_STORE", "source_name": "北区门店"},
        {"id": 31, "report_name": "东区渠道月度经营报告", "metric_ids": json.dumps([1]),
         "report_period": "2026-10", "output_format": "json", "auto_send": 0, "status": "已停用",
         "source_key": "SRC_EAST_CHANNEL", "source_name": "东区渠道"},
    ]
    for report in reports:
        db.insert("reports", report)

    created: list[dict[str, Any]] = []

    def emit(report_id: int, generated_at: str) -> dict[str, Any]:
        report = db.fetchone("SELECT * FROM reports WHERE id=?", [report_id])
        result = generate_report(dict(report))
        db.update("report_outputs", {"generated_at": generated_at}, "id=?", [result["id"]])
        return db.fetchone("SELECT * FROM report_outputs WHERE id=?", [result["id"]]) or {}

    # 41：一次生成，凭据齐全
    out_41 = emit(41, t_41)
    prov.add_attribution(
        out_41["id"], source_key="SRC_NORTH_CHANNEL", source_name="北区渠道",
        status=prov.CONFIRMED, evidence_ref="EV-2026-11-0141",
        evidence_detail="渠道结算回执 2026-11 批次已签章",
        registered_by="档案员", registered_at=t_41,
    )
    db.update("report_outputs", {"source_display_name": "北区渠道"}, "id=?", [out_41["id"]])

    # 42：历史生成，正文只有旧简称“北区”，没有可验证凭据
    out_42 = emit(42, t_42)
    db.update("report_outputs", {"source_display_name": "北区"}, "id=?", [out_42["id"]])
    prov.add_attribution(
        out_42["id"], source_key="", source_name="北区",
        status=prov.PENDING, display_only=True,
        evidence_detail="存量输出正文只写旧简称，尚无回执",
        registered_by="系统导入", registered_at=t_42,
    )

    # 43：后跑的门店报告，来源是北区门店，不能并入北区渠道口径
    out_43 = emit(43, t_43)
    db.update("report_outputs", {"source_display_name": "北区门店"}, "id=?", [out_43["id"]])
    prov.add_attribution(
        out_43["id"], source_key="SRC_NORTH_STORE", source_name="北区门店",
        status=prov.CONFIRMED, evidence_ref="EV-2026-11-0143",
        evidence_detail="门店系统日结回执", registered_by="档案员", registered_at=t_43,
    )

    # 31：上期东区，验证期间/来源交叉筛选
    out_31 = emit(31, t_old)
    db.update("report_outputs", {"source_display_name": "东区"}, "id=?", [out_31["id"]])
    prov.add_attribution(
        out_31["id"], source_key="SRC_EAST_CHANNEL", source_name="东区渠道",
        status=prov.CONFIRMED, evidence_ref="EV-2026-10-0131",
        evidence_detail="东区渠道月结回执", registered_by="档案员", registered_at=t_old,
    )

    created = [
        {"report_id": 41, "output_id": out_41["id"], "output_no": out_41["output_no"]},
        {"report_id": 42, "output_id": out_42["id"], "output_no": out_42["output_no"]},
        {"report_id": 43, "output_id": out_43["id"], "output_no": out_43["output_no"]},
        {"report_id": 31, "output_id": out_31["id"], "output_no": out_31["output_no"]},
    ]
    return {"skipped": False, "reports": len(reports), "outputs": created}
