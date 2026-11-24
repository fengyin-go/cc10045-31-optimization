"""报告快照领域服务：保存报告的完整数据快照并支持历史版本对比。

真实数据流：从 report_outputs 读取已有报告内容 → 生成快照记录写入 snapshots 表
→ 支持两版本对比 → 标记差异快照 → 供趋势分析和版本回溯。

留档口径（本模块关键约束）：
- 快照必须针对“结算员在检索结果里选中的那一条输出”，不能退化成“报告最新一版”；
- 快照固化该输出的编号、生成时点、当时采用的来源与凭据、以及该版指标数据；
- 同一模板后来补跑的新输出不会改写旧快照，旧快照仍保留自身内容。
"""
from __future__ import annotations

import json
from typing import Any

from app.database import db
from app.services import report_provenance as prov
from app.services.base import BaseModuleService


class ReportSnapshotService(BaseModuleService):
    MODULE = "report_snapshot"
    ENTITY = "快照记录"
    OPERATION_TERM = "存储"
    LIST_FIELDS = ["快照名称", "所属报告", "快照时间", "数据摘要", "差异对比"]
    REQUIRED_FIELDS = ["快照名称", "所属报告"]
    STATUS_ORDER = ["已保存", "已对比", "有差异"]
    ACTION_RULES = {"生成快照": "已保存", "对比快照": "已对比"}
    NEGATIVE_ACTIONS = []

    def create_for_report(
        self,
        report_id: int,
        snapshot_name: str,
        *,
        output_id: int | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """从一条选定的报告输出创建快照。

        output_id 缺省时退回该报告最新一条输出（兼容旧调用），
        但页面留档必须显式传入结算员选中的输出编号。
        """
        if not str(snapshot_name or "").strip():
            return {"ok": False, "message": "快照名称不能为空"}

        if output_id is not None:
            output = db.fetchone(
                "SELECT * FROM report_outputs WHERE id=? AND report_id=?",
                [output_id, report_id],
            )
            if output is None:
                return {"ok": False, "message": f"报告 {report_id} 下没有输出 {output_id}，不能引用其它模板的输出"}
        else:
            output = db.fetchone(
                "SELECT * FROM report_outputs WHERE report_id=? "
                "ORDER BY generated_at DESC, id DESC LIMIT 1",
                [report_id],
            )
            if output is None:
                return {"ok": False, "message": f"报告 {report_id} 没有已生成的输出"}

        frozen_at = as_of or prov.precise_now()
        attr = prov.attribution_as_of(output["id"], frozen_at)
        attr_view = prov.attribution_to_view(attr)

        # 输出只有显示名时按“有待翻查”留档，并在快照里标明，绝不丢弃。
        display_only = bool(attr_view["display_only"])
        source_status = attr_view["source_status"]
        source_name = attr_view["source_name"] or output.get("source_display_name")
        source_key = attr_view["source_key"]
        if source_name and attr is None:
            matched = prov.resolve_sources(source_name)
            if matched:
                source_key = matched[0]["source_key"]
                source_name = matched[0]["source_name"]
            source_status = prov.PENDING
            display_only = True
        elif source_name is None:
            source_status = prov.MISSING

        metric_data = prov.extract_metric_data(output["output_content"])
        content = prov.loads(output["output_content"], {})
        summary = {
            "output_id": output["id"],
            "output_no": output.get("output_no") or f"OUT-{output['id']}",
            "business_period": output.get("business_period"),
            "generated_at": output.get("generated_at"),
            "metric_count": len(metric_data),
            "source_name": source_name,
            "source_status": source_status,
        }

        snapshot_id = db.insert("snapshots", {
            "snapshot_name": snapshot_name,
            "report_id": report_id,
            "snapshot_content": output["output_content"],
            "status": "已保存",
            "output_id": output["id"],
            "output_no": output.get("output_no") or f"OUT-{output['id']}",
            "business_period": output.get("business_period"),
            "source_key": source_key,
            "source_name": source_name,
            "source_status": source_status,
            "evidence_ref": attr_view["evidence_ref"],
            "source_as_of": frozen_at,
            "source_display_only": 1 if display_only else 0,
            "metric_data": json.dumps(metric_data, ensure_ascii=False),
        })
        return {
            "ok": True,
            "snapshot_id": snapshot_id,
            "snapshot_name": snapshot_name,
            "report_id": report_id,
            "output_id": output["id"],
            "output_no": summary["output_no"],
            "business_period": output.get("business_period"),
            "source_name": source_name,
            "source_status": source_status,
            "display_only": display_only,
            "evidence_ref": attr_view["evidence_ref"],
            "metric_data": metric_data,
            "summary": summary,
            "snapshot_content": content,
        }

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        row = db.fetchone("SELECT * FROM snapshots WHERE id=?", [snapshot_id])
        if row is None:
            return None
        row["snapshot_content"] = prov.loads(row.get("snapshot_content"), {})
        row["metric_data"] = prov.loads(row.get("metric_data"), [])
        row["comparison_diff"] = prov.loads(row.get("comparison_diff"), None)
        row["source_display_only"] = bool(row.get("source_display_only"))
        return row

    def verify_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        """从快照本身核对：输出编号、当时来源、该版指标数据。

        故意不回读 report_outputs，确保后续补跑/改来源都不影响这份留档。
        """
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            return None
        metric_data = snapshot["metric_data"]
        content_sections = (snapshot["snapshot_content"] or {}).get("sections", [])
        return {
            "snapshot_id": snapshot["id"],
            "snapshot_name": snapshot["snapshot_name"],
            "report_id": snapshot["report_id"],
            "output_id": snapshot["output_id"],
            "output_no": snapshot["output_no"],
            "business_period": snapshot["business_period"],
            "frozen_at": snapshot["source_as_of"],
            "created_at": snapshot["created_at"],
            "source": {
                "source_key": snapshot["source_key"],
                "source_name": snapshot["source_name"],
                "source_status": snapshot["source_status"],
                "evidence_ref": snapshot["evidence_ref"],
                "display_only": snapshot["source_display_only"],
            },
            "metric_data": metric_data,
            "content_metric_count": len(content_sections),
            "metric_data_matches_content": len(content_sections) == len(metric_data),
            "complete": bool(snapshot["output_id"]) and (
                snapshot["source_status"] == prov.CONFIRMED or snapshot["source_status"] == prov.PENDING
            ),
        }

    def compare_snapshots(self, snapshot_id_a: int, snapshot_id_b: int) -> dict[str, Any]:
        """对比两个快照的差异。"""
        a = db.fetchone("SELECT * FROM snapshots WHERE id=?", [snapshot_id_a])
        b = db.fetchone("SELECT * FROM snapshots WHERE id=?", [snapshot_id_b])

        if not a or not b:
            return {"ok": False, "message": "快照不存在"}

        try:
            content_a = json.loads(a["snapshot_content"]) if isinstance(a["snapshot_content"], str) else a["snapshot_content"]
            content_b = json.loads(b["snapshot_content"]) if isinstance(b["snapshot_content"], str) else b["snapshot_content"]
        except json.JSONDecodeError:
            return {"ok": False, "message": "快照内容解析失败"}

        diffs = []
        sections_a = content_a.get("sections", [])
        sections_b = content_b.get("sections", [])

        for sa, sb in zip(sections_a, sections_b):
            val_a = sa.get("current_value", 0)
            val_b = sb.get("current_value", 0)
            if val_a and val_b:
                try:
                    diff_pct = round(float(val_a - val_b) / max(abs(float(val_b)), 0.0001) * 100, 2)
                    diffs.append({
                        "metric": sa.get("metric_name"),
                        "value_a": val_a,
                        "value_b": val_b,
                        "diff_pct": diff_pct,
                        "has_diff": abs(diff_pct) > 1.0,
                    })
                except (TypeError, ValueError):
                    pass

        has_diff = any(d["has_diff"] for d in diffs)
        comparison_summary = {
            "snapshot_a": snapshot_id_a,
            "snapshot_b": snapshot_id_b,
            "output_no_a": a.get("output_no"),
            "output_no_b": b.get("output_no"),
            "total_metrics": len(diffs),
            "diffs_found": sum(1 for d in diffs if d["has_diff"]),
            "details": diffs,
        }

        db.update("snapshots", {
            "status": "已对比" if not has_diff else "有差异",
            "comparison_diff": json.dumps(comparison_summary, ensure_ascii=False),
        }, "id=?", [snapshot_id_a])

        return {"ok": True, "has_difference": has_diff, "summary": comparison_summary}

    def report_snapshots(self, report_id: int) -> list[dict[str, Any]]:
        """获取报告的所有快照。"""
        rows = db.fetchall(
            "SELECT * FROM snapshots WHERE report_id=? ORDER BY created_at DESC, id DESC",
            [report_id],
        )
        return [self._hydrate(row) for row in rows]

    def report_snapshots_all(self) -> list[dict[str, Any]]:
        rows = db.fetchall("SELECT * FROM snapshots ORDER BY created_at DESC, id DESC")
        return [self._hydrate(row) for row in rows]

    @staticmethod
    def _hydrate(row: dict[str, Any]) -> dict[str, Any]:
        row["snapshot_content"] = prov.loads(row.get("snapshot_content"), {})
        row["metric_data"] = prov.loads(row.get("metric_data"), [])
        row["search_summary"] = {
            "output_no": row.get("output_no"),
            "source_name": row.get("source_name"),
            "source_status": row.get("source_status"),
            "business_period": row.get("business_period"),
            "metric_count": len(row["metric_data"]),
            "display_only": bool(row.get("source_display_only")),
        }
        row["source_display_only"] = bool(row.get("source_display_only"))
        return row

    def domain_snapshot(self) -> dict[str, Any]:
        snapshot = super().domain_snapshot()
        snapshot["total_snapshots"] = db.count("snapshots")
        return snapshot
