"""报告取数来源与凭据：来源别名解析、按查验时点还原归属。

设计要点：
- `report_sources` 只存来源的规范键、显示名和历史旧简称；
- `report_source_attributions` 是只追加的凭据登记流水，同一份报告输出可以先后补登多条；
- 检索/下发/快照都按某个查验时点取“该时点之前最近的一条”凭据，
  因此筛选时点的判定结果不会被之后补登的凭据改写。

旧存量输出正文里只有显示名（如“北区”）时，不删除记录：
显示名经别名解析到规范来源，但状态标为“有待翻查”，直到有可验证凭据。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database import db

CONFIRMED = "已确认"
PENDING = "有待翻查"
MISSING = "来源缺失"

# 时间戳带微秒，避免同一秒内“先检索、后补登”被当成同一时点。
def precise_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


# 兼容仍按旧名调用的地方
_loads = loads


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


# 供其它模块做大小写/空白归一比较
norm = _norm


def source_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    aliases = _loads(row.get("aliases"), [])
    return {
        "source_key": row["source_key"],
        "source_name": row["source_name"],
        "aliases": [str(a) for a in aliases if str(a).strip()],
        "source_type": row.get("source_type", ""),
        "status": row.get("status", CONFIRMED),
    }


def list_sources() -> list[dict[str, Any]]:
    rows = db.fetchall("SELECT * FROM report_sources ORDER BY source_key")
    return [source_row_to_dict(row) for row in rows]


def find_source_by_key(source_key: str) -> dict[str, Any] | None:
    if not source_key:
        return None
    row = db.fetchone("SELECT * FROM report_sources WHERE source_key=?", [source_key])
    return source_row_to_dict(row) if row else None


def resolve_sources(query: str | None) -> list[dict[str, Any]]:
    """把用户输入的来源（规范名或旧简称）解析为一条或多条来源。

    先做“规范名/别名全等”匹配，命中即只返回这些来源；
    只有在没有任何全等命中时才退回规范名包含匹配。
    这样检索“北区”会命中别名为“北区”的“北区渠道”，不会把“北区门店”带进来。
    """
    text = _norm(query)
    if not text:
        return []
    sources = list_sources()
    exact = [
        src for src in sources
        if _norm(src["source_name"]) == text
        or any(_norm(alias) == text for alias in src["aliases"])
    ]
    if exact:
        return exact
    return [
        src for src in sources
        if text in _norm(src["source_name"])
        or any(text in _norm(alias) for alias in src["aliases"])
    ]


def source_matches_query(source_key: str | None, source_name: str | None, query: str | None) -> bool:
    """判断一条已归属来源的记录是否落在检索口径内。"""
    if not _norm(query):
        return True
    resolved = resolve_sources(query)
    if resolved:
        keys = {src["source_key"] for src in resolved}
        if source_key in keys:
            return True
        # 没有规范键的存量记录，退回显示名和别名比对
        return any(
            _norm(source_name) == _norm(src["source_name"])
            or any(_norm(source_name) == _norm(alias) for alias in src["aliases"])
            for src in resolved
        )
    text = _norm(query)
    return text in _norm(source_name)


def ensure_source(name: str, *, source_key: str | None = None,
                  source_type: str = "", aliases: list[str] | None = None) -> dict[str, Any]:
    """按规范名查找来源，不存在则登记；可补充别名。"""
    clean = str(name or "").strip()
    if not clean:
        raise ValueError("来源名称不能为空")
    if source_key:
        existing = find_source_by_key(source_key)
        if existing:
            return existing
    normalized = _norm(clean)
    for src in list_sources():
        if _norm(src["source_name"]) == normalized or any(
            _norm(alias) == normalized for alias in src["aliases"]
        ):
            return src

    key = source_key or f"SRC_{abs(hash(clean)) % 10_000_000:07d}"
    db.insert("report_sources", {
        "source_key": key,
        "source_name": clean,
        "aliases": json.dumps(aliases or [], ensure_ascii=False),
        "source_type": source_type,
        "status": CONFIRMED,
    })
    return find_source_by_key(key) or {}


def add_attribution(
    output_id: int,
    *,
    source_key: str | None,
    source_name: str,
    status: str = CONFIRMED,
    evidence_ref: str | None = None,
    evidence_detail: str | None = None,
    display_only: bool = False,
    registered_by: str = "",
    registered_at: str | None = None,
) -> dict[str, Any]:
    clean_status = status if status in (CONFIRMED, PENDING) else PENDING
    attribution_id = db.insert("report_source_attributions", {
        "output_id": output_id,
        "source_key": source_key or "",
        "source_name": source_name or "",
        "status": clean_status,
        "evidence_ref": evidence_ref or None,
        "evidence_detail": evidence_detail or None,
        "display_only": 1 if display_only else 0,
        "registered_by": registered_by or "",
        "registered_at": registered_at or precise_now(),
    })
    return db.fetchone("SELECT * FROM report_source_attributions WHERE id=?", [attribution_id]) or {}


def attribution_as_of(output_id: int, as_of: str | None) -> dict[str, Any] | None:
    """取该输出在 as_of 时点生效的来源归属。

    以“该时点之前最近的一条记录”为准，只有一种例外：
    如果最近一条只是“仅显示名”的备注（display_only），而此前已有带凭据的已确认归属，
    则沿用那条已确认归属——补一句显示名不能把已确认来源悄悄降级。
    要真正改口径，请登记一条明确的状态（pending 或新的带凭据 confirmed）。
    """
    params: list[Any] = [output_id]
    time_clause = ""
    if as_of:
        time_clause = "AND registered_at<=?"
        params.append(as_of)

    rows = db.fetchall(
        "SELECT * FROM report_source_attributions "
        f"WHERE output_id=? {time_clause} "
        "ORDER BY registered_at DESC, id DESC",
        params,
    )
    if not rows:
        return None
    chosen = rows[0]
    if chosen.get("display_only") and chosen.get("status") != CONFIRMED:
        for row in rows[1:]:
            if row.get("status") == CONFIRMED and row.get("evidence_ref") \
                    and not row.get("display_only"):
                chosen = row
                break
    chosen["display_only"] = bool(chosen.get("display_only"))
    return chosen


def attribution_to_view(attr: dict[str, Any] | None) -> dict[str, Any]:
    if attr is None:
        return {
            "source_key": None,
            "source_name": None,
            "source_status": MISSING,
            "display_only": False,
            "evidence_ref": None,
            "evidence_detail": None,
            "evidence_registered_at": None,
            "attribution_id": None,
        }
    return {
        "source_key": attr.get("source_key") or None,
        "source_name": attr.get("source_name") or None,
        "source_status": attr.get("status") or PENDING,
        "display_only": bool(attr.get("display_only")),
        "evidence_ref": attr.get("evidence_ref"),
        "evidence_detail": attr.get("evidence_detail"),
        "evidence_registered_at": attr.get("registered_at"),
        "attribution_id": attr.get("id"),
    }


def is_dispatchable(attr_view: dict[str, Any]) -> bool:
    """只有带可验证凭据的已确认来源才能下发核数。"""
    return (
        attr_view.get("source_status") == CONFIRMED
        and bool(attr_view.get("evidence_ref"))
        and not attr_view.get("display_only")
        and bool(attr_view.get("source_key") or attr_view.get("source_name"))
    )


def extract_metric_data(output_content: Any) -> list[dict[str, Any]]:
    """从报告输出正文里抽出该版指标数据，供快照和核数批逐条核对。"""
    content = _loads(output_content, {})
    sections = content.get("sections") if isinstance(content, dict) else None
    if not isinstance(sections, list):
        return []
    metrics: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        metrics.append({
            "metric_name": section.get("metric_name"),
            "metric_type": section.get("metric_type"),
            "unit": section.get("unit", ""),
            "current_value": section.get("current_value"),
            "baseline": section.get("baseline"),
            "status": section.get("status"),
        })
    return metrics
