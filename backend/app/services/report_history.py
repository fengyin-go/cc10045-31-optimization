"""报告历史检索与核数批次领域服务。

三件事在这里闭环：
1. 检索：按业务期间、指标取数来源、指标检索实际生成的报告输出（report_outputs），
   每条输出按“查验时点”还原它的来源归属；正文里只有显示名的存量输出保留，
   并标明“已确认”还是“有待翻查”。
2. 下发核数：只把有可验证来源凭据的输出派给经办人；批次范围在下发时冻结，
   之后补登凭据或改确认状态都不改写已发批次；筛选后补登的凭据在批次里
   明确写“本批下发”还是“留待下次核数”。
3. 留档：按选中的那一份输出生成快照，快照固化输出编号、当时来源、该版指标数据。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database import db
from app.services import report_provenance as prov
from app.services.base import BaseModuleService


class ReportHistoryService(BaseModuleService):
    MODULE = "data_report"
    ENTITY = "报告输出"

    # ==================================================================
    # 检索
    # ==================================================================

    def search_outputs(
        self,
        *,
        business_period: str | None = None,
        source: str | None = None,
        metric: str | None = None,
        keyword: str | None = None,
        as_of: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        """按期间/来源/指标检索报告输出，返回条目、总数和本次查验上下文。"""
        verified_at = as_of or prov.precise_now()
        rows = db.fetchall(
            "SELECT o.*, r.report_name AS r_report_name, r.metric_ids AS r_metric_ids, "
            "r.report_period AS r_report_period, r.source_key AS r_source_key, "
            "r.source_name AS r_source_name "
            "FROM report_outputs o LEFT JOIN reports r ON r.id = o.report_id "
            "ORDER BY o.generated_at DESC, o.id DESC"
        )
        resolved = prov.resolve_sources(source)
        items: list[dict[str, Any]] = []

        for row in rows:
            item = self._build_item(row, verified_at)
            if business_period and business_period.strip() not in str(item["business_period"] or ""):
                continue
            if source and not self._source_in_scope(item, resolved, source):
                continue
            if metric:
                names = [str(m.get("metric_name") or "") for m in item["metric_data"]]
                if not any(metric.strip() in name for name in names):
                    continue
            if keyword:
                haystack = " ".join(str(item.get(k) or "") for k in (
                    "output_no", "report_name", "business_period", "source_name"))
                if keyword.strip() not in haystack:
                    continue
            items.append(item)

        total = len(items)
        start = max(page - 1, 0) * size
        paged = items[start:start + size]
        context = {
            "verified_at": verified_at,
            "source_query": source,
            "resolved_sources": resolved,
            "business_period": business_period,
            "metric": metric,
        }
        return paged, total, context

    def _build_item(self, row: dict[str, Any], as_of: str) -> dict[str, Any]:
        attr_view = prov.attribution_to_view(prov.attribution_as_of(row["id"], as_of))
        metric_data = prov.extract_metric_data(row.get("output_content"))
        report_name = row.get("r_report_name") or ""
        business_period = row.get("business_period") or row.get("r_report_period") or ""
        source_name = attr_view["source_name"] or row.get("r_source_name") or row.get("source_display_name")

        # 存量输出正文里只有显示名：记录保留，尝试把显示名解析成规范来源，
        # 但状态仍是“有待翻查”，因为显示名本身不构成可验证凭据。
        if attr_view["source_status"] != prov.CONFIRMED and source_name:
            matched = prov.resolve_sources(source_name)
            if matched:
                attr_view["source_key"] = matched[0]["source_key"]
                attr_view["source_name"] = matched[0]["source_name"]
                source_name = matched[0]["source_name"]
            attr_view["display_only"] = True
            attr_view["source_status"] = prov.PENDING

        dispatchable = prov.is_dispatchable({**attr_view, "source_name": source_name})
        if attr_view["source_status"] == prov.MISSING:
            status_label, status_reason = "来源缺失", "没有任何来源归属，不能下发核数"
        elif dispatchable:
            status_label, status_reason = "来源已确认", "有可验证凭据，可下发核数"
        elif attr_view["display_only"]:
            status_label, status_reason = "有待翻查", "正文只有显示名，待补可验证来源凭据"
        else:
            status_label, status_reason = "有待翻查", "来源尚未登记可验证凭据"

        # 这条版本是否已被某个已发核数批覆盖：已覆盖的不用重复发，未覆盖且可下发的才是待继续核对。
        coverage = self._coverage(row["id"])

        return {
            "output_id": row["id"],
            "output_no": row.get("output_no") or f"OUT-{row['id']}",
            "report_id": row.get("report_id"),
            "report_name": report_name,
            "business_period": business_period,
            "generated_at": row.get("generated_at"),
            "source_key": attr_view["source_key"],
            "source_name": source_name,
            "display_name": row.get("source_display_name") or attr_view["source_name"],
            "source_status": attr_view["source_status"],
            "status_label": status_label,
            "status_reason": status_reason,
            "display_only": bool(attr_view["display_only"]),
            "evidence_ref": attr_view["evidence_ref"],
            "evidence_registered_at": attr_view["evidence_registered_at"],
            "attribution_id": attr_view["attribution_id"],
            "metric_data": metric_data,
            "metric_names": [m.get("metric_name") for m in metric_data],
            "dispatchable": dispatchable,
            "verified_at": as_of,
            "attribution_count": db.count(
                "report_source_attributions", "output_id=?", [row["id"]]),
            "already_dispatched": coverage["dispatched"],
            "dispatched_batches": coverage["batch_nos"],
            "needs_reconciliation": dispatchable and not coverage["dispatched"],
        }

    def _coverage(self, output_id: int) -> dict[str, Any]:
        rows = db.fetchall(
            "SELECT b.batch_no FROM reconciliation_batch_items i "
            "JOIN reconciliation_batches b ON b.id = i.batch_id "
            "WHERE i.output_id=? ORDER BY b.dispatched_at",
            [output_id],
        )
        nos = [r["batch_no"] for r in rows]
        return {"dispatched": bool(nos), "batch_nos": nos}

    @staticmethod
    def _source_in_scope(item: dict[str, Any], resolved: list[dict[str, Any]],
                         raw_query: str) -> bool:
        if resolved:
            keys = {src["source_key"] for src in resolved}
            if item.get("source_key") in keys:
                return True
            name = str(item.get("source_name") or "")
            return any(
                prov.norm(name) == prov.norm(src["source_name"])
                or any(prov.norm(name) == prov.norm(alias) for alias in src["aliases"])
                for src in resolved
            )
        return prov.norm(raw_query) in prov.norm(item.get("source_name"))

    def get_output(self, output_id: int, as_of: str | None = None) -> dict[str, Any] | None:
        row = db.fetchone(
            "SELECT o.*, r.report_name AS r_report_name, r.metric_ids AS r_metric_ids, "
            "r.report_period AS r_report_period, r.source_key AS r_source_key, "
            "r.source_name AS r_source_name "
            "FROM report_outputs o LEFT JOIN reports r ON r.id = o.report_id WHERE o.id=?",
            [output_id],
        )
        if row is None:
            return None
        return self._build_item(row, as_of or prov.precise_now())

    # ==================================================================
    # 来源与凭据登记
    # ==================================================================

    def register_attribution(
        self,
        output_id: int,
        *,
        source_name: str,
        source_key: str | None = None,
        status: str = prov.CONFIRMED,
        evidence_ref: str | None = None,
        evidence_detail: str | None = None,
        display_only: bool = False,
        registered_by: str = "",
        registered_at: str | None = None,
    ) -> dict[str, Any]:
        output = db.fetchone("SELECT * FROM report_outputs WHERE id=?", [output_id])
        if output is None:
            return {"ok": False, "message": f"报告输出 {output_id} 不存在"}

        clean_name = str(source_name or "").strip()
        if not clean_name:
            return {"ok": False, "message": "登记来源必须填写来源名称"}

        source = prov.find_source_by_key(source_key) if source_key else None
        if source is None:
            matched = prov.resolve_sources(clean_name)
            source = matched[0] if matched else None
        if source is None and status == prov.CONFIRMED and evidence_ref:
            source = prov.ensure_source(clean_name, source_type="登记来源")

        resolved_key = (source or {}).get("source_key") or source_key
        resolved_name = (source or {}).get("source_name") or clean_name

        if display_only:
            # 明确“只登记显示名”：作为备注，不降级此前已确认的来源
            clean_status = prov.PENDING
        elif status == prov.PENDING:
            # 明确判定为待翻查（可带凭据说明）：这是一次真正的口径变更
            clean_status = prov.PENDING
            display_only = False
        else:
            clean_status = prov.CONFIRMED if status == prov.CONFIRMED else prov.PENDING
            if clean_status == prov.CONFIRMED and not evidence_ref:
                return {"ok": False, "message": "来源确认必须附可验证凭据编号，不能只填显示名"}

        attr = prov.add_attribution(
            output_id,
            source_key=resolved_key,
            source_name=resolved_name,
            status=clean_status,
            evidence_ref=evidence_ref,
            evidence_detail=evidence_detail,
            display_only=display_only,
            registered_by=registered_by,
            registered_at=registered_at,
        )
        return {"ok": True, "message": "来源凭据已登记", "attribution": attr,
                "output": self.get_output(output_id)}

    def attribution_history(self, output_id: int) -> list[dict[str, Any]]:
        rows = db.fetchall(
            "SELECT * FROM report_source_attributions WHERE output_id=? "
            "ORDER BY registered_at ASC, id ASC",
            [output_id],
        )
        for row in rows:
            row["display_only"] = bool(row.get("display_only"))
        return rows

    # ==================================================================
    # 下发核数
    # ==================================================================

    def dispatch_batch(
        self,
        *,
        business_period: str,
        source: str | None,
        metric: str | None = None,
        verify_mode: str = "filter_time",
        filtered_at: str | None = None,
        dispatched_by: str = "",
        note: str = "",
        dry_run: bool = False,
        dispatched_at: str | None = None,
    ) -> dict[str, Any]:
        if not str(business_period or "").strip():
            return {"ok": False, "message": "下发核数必须指定业务期间"}
        if verify_mode not in ("filter_time", "dispatch_time"):
            return {"ok": False, "message": "未知的核验口径"}

        dispatched_at = dispatched_at or prov.precise_now()
        if verify_mode == "filter_time":
            if not filtered_at:
                return {"ok": False, "message": "按开始筛选时核验需要提供筛选时点"}
            verify_as_of = filtered_at
        else:
            verify_as_of = dispatched_at

        plan = self._plan_roster(
            business_period=business_period, source=source, metric=metric,
            verify_mode=verify_mode, filtered_at=filtered_at or dispatched_at,
            verify_as_of=verify_as_of, dispatched_at=dispatched_at,
        )
        if dry_run:
            return {"ok": True, "dry_run": True, "message": "试算完成，未写入", **plan}
        if not plan["roster"]:
            return {"ok": False,
                    "message": "本次查验没有可下发的报告输出：缺来源证据的记录不能下发核数",
                    "deferrals": plan["deferrals"]}

        batch_no = self._next_batch_no(dispatched_at)
        batch_id = db.insert("reconciliation_batches", {
            "batch_no": batch_no,
            "business_period": business_period,
            "source_key": plan["source_key"],
            "source_name": source or "",
            "verify_mode": verify_mode,
            "filtered_at": filtered_at or dispatched_at,
            "as_of": verify_as_of,
            "metric_scope": json.dumps([metric] if metric else [], ensure_ascii=False),
            "dispatched_by": dispatched_by,
            "dispatched_at": dispatched_at,
            "item_count": len(plan["roster"]),
            "note": note,
        })

        for entry in plan["roster"]:
            db.insert("reconciliation_batch_items", {
                "batch_id": batch_id,
                **entry,
                "metric_data": json.dumps(entry["metric_data"], ensure_ascii=False),
            })

        for deferred in plan["deferrals"]:
            db.insert("reconciliation_batch_deferrals", {"batch_id": batch_id, **deferred})

        return {"ok": True,
                "message": f"核数批 {batch_no} 已下发 {len(plan['roster'])} 条",
                "batch": self.get_batch(batch_id)}

    def _plan_roster(
        self,
        *,
        business_period: str,
        source: str | None,
        metric: str | None,
        verify_mode: str,
        filtered_at: str,
        verify_as_of: str,
        dispatched_at: str,
    ) -> dict[str, Any]:
        """按核验口径算出名单和留待清单，不落库（下发和试算共用）。"""
        scope_items, _, _ = self.search_outputs(
            business_period=business_period, source=source, metric=metric,
            as_of=verify_as_of, page=1, size=1_000_000,
        )
        roster: list[dict[str, Any]] = []
        deferrals: list[dict[str, Any]] = []

        for item in scope_items:
            if item["dispatchable"]:
                roster.append(self._roster_entry(item, verify_mode, filtered_at))
                continue

            later = self._latest_dispatchable_between(
                item["output_id"], max(verify_as_of, filtered_at), dispatched_at)
            if later is not None:
                deferrals.append({
                    "output_id": item["output_id"],
                    "output_no": item["output_no"],
                    "source_name": later.get("source_name") or item["source_name"],
                    "evidence_ref": later.get("evidence_ref"),
                    "evidence_registered_at": later.get("registered_at"),
                    "disposition": "留待下次核数",
                    "reason": "凭据在开始筛选后补登；本批按筛选时点口径未纳入，留待下次核数",
                })
            else:
                deferrals.append({
                    "output_id": item["output_id"],
                    "output_no": item["output_no"],
                    "source_name": item["source_name"],
                    "evidence_ref": None,
                    "evidence_registered_at": None,
                    "disposition": "留待下次核数",
                    "reason": item["status_reason"] + "；凭据补齐后再下发",
                })

        resolved = prov.resolve_sources(source)
        return {
            "scope_count": len(scope_items),
            "source_key": resolved[0]["source_key"] if resolved else None,
            "verify_as_of": verify_as_of,
            "roster": roster,
            "deferrals": deferrals,
        }

    def _roster_entry(self, item: dict[str, Any], verify_mode: str,
                      filtered_at: str) -> dict[str, Any]:
        evidence_late = 0
        disposition = "本批下发"
        if verify_mode == "dispatch_time":
            first_ok_at = self._first_dispatchable_at(item["output_id"])
            if first_ok_at and filtered_at and first_ok_at > filtered_at:
                evidence_late = 1
                disposition = "本批下发（筛选后补登凭据，已在本批改按最新核验纳入）"
        return {
            "output_id": item["output_id"],
            "output_no": item["output_no"],
            "report_id": item["report_id"],
            "report_name": item["report_name"],
            "business_period": item["business_period"],
            "source_key": item["source_key"],
            "source_name": item["source_name"],
            "source_status": item["source_status"],
            "evidence_ref": item["evidence_ref"],
            "evidence_registered_at": item["evidence_registered_at"],
            "selected_attribution_id": item.get("attribution_id"),
            "evidence_late": evidence_late,
            "disposition": disposition,
            "metric_data": item["metric_data"],
            "generated_at": item["generated_at"],
            "verify_mode": verify_mode,
            "selected_source_status": item["status_label"],
        }

    def _latest_dispatchable_between(
        self, output_id: int, after: str, until: str,
    ) -> dict[str, Any] | None:
        rows = db.fetchall(
            "SELECT * FROM report_source_attributions WHERE output_id=? "
            "AND registered_at>? AND registered_at<=? "
            "ORDER BY registered_at DESC, id DESC",
            [output_id, after, until],
        )
        for row in rows:
            view = prov.attribution_to_view(row)
            if prov.is_dispatchable(view):
                return row
        return None

    def _first_dispatchable_at(self, output_id: int) -> str | None:
        rows = db.fetchall(
            "SELECT * FROM report_source_attributions WHERE output_id=? "
            "ORDER BY registered_at ASC, id ASC",
            [output_id],
        )
        for row in rows:
            if prov.is_dispatchable(prov.attribution_to_view(row)):
                return row["registered_at"]
        return None

    @staticmethod
    def _next_batch_no(at: str) -> str:
        day = at[:10].replace("-", "")
        prefix = f"RC{day}-"
        existing = db.fetchall(
            "SELECT batch_no FROM reconciliation_batches WHERE batch_no LIKE ?",
            [f"{prefix}%"],
        )
        return f"{prefix}{len(existing) + 1}"

    # ==================================================================
    # 批次回看（冻结名单）
    # ==================================================================

    def list_batches(self) -> list[dict[str, Any]]:
        rows = db.fetchall(
            "SELECT * FROM reconciliation_batches ORDER BY dispatched_at DESC, id DESC")
        for row in rows:
            row["items"] = db.count(
                "reconciliation_batch_items", "batch_id=?", [row["id"]])
            row["deferrals"] = db.count(
                "reconciliation_batch_deferrals", "batch_id=?", [row["id"]])
        return rows

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        batch = db.fetchone("SELECT * FROM reconciliation_batches WHERE id=?", [batch_id])
        if batch is None:
            return None
        items = db.fetchall(
            "SELECT * FROM reconciliation_batch_items WHERE batch_id=? ORDER BY id",
            [batch_id],
        )
        for item in items:
            item["metric_data"] = prov.loads(item.get("metric_data"), [])
            item["evidence_late"] = bool(item.get("evidence_late"))
            # 逐条核对：这条当年采用的是哪个来源、哪份凭据
            item["attribution_trace"] = self._attribution_trace(
                item.get("selected_attribution_id"),
                item["output_id"], item.get("evidence_registered_at"))
        deferrals = db.fetchall(
            "SELECT * FROM reconciliation_batch_deferrals WHERE batch_id=? ORDER BY id",
            [batch_id],
        )
        batch["metric_scope"] = prov.loads(batch.get("metric_scope"), [])
        batch["items"] = items
        batch["deferrals"] = deferrals
        batch["frozen"] = True
        return batch

    @staticmethod
    def _attribution_trace(attribution_id: int | None, output_id: int,
                           evidence_registered_at: str | None) -> dict[str, Any]:
        """批次发出后仍能逐条核对：锁定下发时实际采用的那一条凭据。

        优先按登记记录主键回查（唯一）；早期数据没有主键时退回按登记时点回查。
        """
        if attribution_id:
            row = db.fetchone(
                "SELECT * FROM report_source_attributions WHERE id=? AND output_id=?",
                [attribution_id, output_id],
            )
        elif evidence_registered_at:
            row = db.fetchone(
                "SELECT * FROM report_source_attributions WHERE output_id=? "
                "AND registered_at=? ORDER BY id DESC LIMIT 1",
                [output_id, evidence_registered_at],
            )
        else:
            row = None
        if row is None:
            return {"locked": False, "reason": "本批采用的来源凭据登记记录不可用"}
        return {
            "locked": True,
            "source_key": row.get("source_key"),
            "source_name": row.get("source_name"),
            "status": row.get("status"),
            "evidence_ref": row.get("evidence_ref"),
            "evidence_detail": row.get("evidence_detail"),
            "registered_by": row.get("registered_by"),
            "registered_at": row.get("registered_at"),
        }


report_history_service = ReportHistoryService()
