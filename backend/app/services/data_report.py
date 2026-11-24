"""数据报告领域服务：管理周期性分析报告的模板配置和自动生成。

真实数据流：定义报告模板（包含指标集/周期/输出格式）→ pipeline.generate_report 读取最新指标值
→ 组装结构化报告内容 → 写入 report_outputs → 快照管理。
"""
from __future__ import annotations

import json
from typing import Any

from app.database import db
from app.pipeline import generate_report
from app.services.base import BaseModuleService


def _maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


class DataReportService(BaseModuleService):
    MODULE = "data_report"
    ENTITY = "报告生成器"
    OPERATION_TERM = "生成"
    LIST_FIELDS = ["报告名称", "包含指标集", "报告周期", "输出格式", "自动发送"]
    REQUIRED_FIELDS = ["报告名称", "包含指标集", "报告周期"]
    STATUS_ORDER = ["草稿", "已发布", "已停用"]
    ACTION_RULES = {"发布报告": "已发布", "停用报告": "已停用"}
    NEGATIVE_ACTIONS = []

    def generate(self, report_id: int) -> dict[str, Any]:
        """生成一次数据报告。"""
        report = db.fetchone("SELECT * FROM reports WHERE id=?", [report_id])
        if report is None:
            return {"ok": False, "message": f"报告 {report_id} 不存在"}

        result = generate_report(dict(report))
        return {
            "ok": True,
            "output_id": result["id"],
            "output_no": result.get("output_no"),
            "report_name": result["report_name"],
            "business_period": result.get("business_period"),
            "summary": result["summary"],
        }

    def recent_outputs(self, report_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """获取报告的历史生成结果，并带上按当前时点还原的来源状态。

        同一模板补跑出来的新输出会出现在列表最前面，
        但已生成的旧输出及其正文保持原样，历史检索仍能单独选中它们。
        """
        from app.services.report_history import report_history_service

        rows = db.fetchall(
            "SELECT * FROM report_outputs WHERE report_id=? "
            "ORDER BY generated_at DESC, id DESC LIMIT ?",
            [report_id, limit],
        )
        outputs: list[dict[str, Any]] = []
        for r in rows:
            view = report_history_service.get_output(r["id"])
            if view is None:
                continue
            view["output_content"] = _maybe_json(r.get("output_content"))
            outputs.append(view)
        return outputs

    def compare_outputs(self, output_id_a: int, output_id_b: int) -> dict[str, Any]:
        """对比两份报告输出的差异。"""
        a = db.fetchone("SELECT * FROM report_outputs WHERE id=?", [output_id_a])
        b = db.fetchone("SELECT * FROM report_outputs WHERE id=?", [output_id_b])
        if not a or not b:
            return {"ok": False, "message": "报告输出不存在"}

        try:
            content_a = json.loads(a["output_content"]) if isinstance(a["output_content"], str) else a["output_content"]
            content_b = json.loads(b["output_content"]) if isinstance(b["output_content"], str) else b["output_content"]
        except json.JSONDecodeError:
            return {"ok": False, "message": "内容解析失败"}

        diffs = []
        sections_a = content_a.get("sections", [])
        sections_b = content_b.get("sections", [])

        for sa, sb in zip(sections_a, sections_b):
            val_a = sa.get("current_value", 0)
            val_b = sb.get("current_value", 0)
            if val_a and val_b and val_a != 0:
                pct = round((val_a - val_b) / abs(val_a) * 100, 2)
                if abs(pct) > 5:
                    diffs.append({
                        "metric": sa.get("metric_name"),
                        "value_a": val_a,
                        "value_b": val_b,
                        "diff_pct": pct,
                    })

        return {
            "ok": True,
            "output_a_time": a["generated_at"],
            "output_b_time": b["generated_at"],
            "significant_diffs": len(diffs),
            "diffs": diffs,
        }

    def domain_snapshot(self) -> dict[str, Any]:
        snapshot = super().domain_snapshot()
        snapshot["total_reports"] = db.count("reports")
        snapshot["total_outputs"] = db.count("report_outputs")
        return snapshot