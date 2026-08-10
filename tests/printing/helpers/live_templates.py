from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from yunprint.plan_builder import context_from_live_template
from yunprint.reports import ReportContext


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "live_templates"

REPORT_FIXTURES = {
    "sales": {
        "logical_name": "销售单",
        "report_type": 1,
        "detail_table": "销售明细",
        "path": "sales.json",
    },
    "purchase": {
        "logical_name": "进货单",
        "report_type": 2,
        "detail_table": "进货明细",
        "path": "purchase.json",
    },
    "payment": {
        "logical_name": "付款单",
        "report_type": 3,
        "detail_table": "付款明细",
        "path": "payment.json",
    },
    "sales-order": {
        "logical_name": "销售订单",
        "report_type": 4,
        "detail_table": "销售订单明细",
        "path": "sales-order.json",
    },
    "inventory-status": {
        "logical_name": "库存状况表",
        "report_type": 5,
        "detail_table": "库存明细",
        "path": "inventory-status.json",
    },
}


def live_template(slug: str) -> dict[str, Any]:
    fixture = REPORT_FIXTURES[slug]
    return json.loads((FIXTURE_ROOT / fixture["path"]).read_text(encoding="utf-8"))


def live_context(slug: str) -> ReportContext:
    fixture = REPORT_FIXTURES[slug]
    return context_from_live_template(
        logical_name=str(fixture["logical_name"]),
        report_type=int(fixture["report_type"]),
        detail_table=str(fixture["detail_table"]),
        template=deepcopy(live_template(slug)),
    )
