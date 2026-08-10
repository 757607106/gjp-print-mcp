"""纯转换函数：将计划输入、线上模板转换为领域对象与报表上下文。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .catalog import FieldCatalog, extract_bindings
from .domain import (
    BorderPlan,
    PagePlan,
    TableStylePlan,
    TemplatePlan,
    TextStylePlan,
)
from .native import content_hash
from .planner import build_plan
from .reports import ReportContext, ReportProfile, page_plan_from_template
from .template_schema import TemplatePlanInput


def context_from_live_template(
    logical_name: str,
    report_type: int,
    detail_table: str,
    template: dict[str, Any],
) -> ReportContext:
    native_name = str(template.get("ReportName") or logical_name)
    digest = content_hash(template)
    catalog = FieldCatalog.from_native_template(
        template,
        report_type=report_type,
        default_detail_table=detail_table,
    )
    slug = "live-" + "".join(
        char.casefold() if char.isalnum() else "-"
        for char in ("%s-%s" % (logical_name, report_type))
    ).strip("-")
    profile = ReportProfile(
        slug=slug,
        logical_name=logical_name,
        native_report_name=native_name,
        aliases=(logical_name, native_name),
        detail_table=detail_table,
    )
    return ReportContext(
        profile=profile,
        base_template=deepcopy(template),
        base_hash=digest,
        catalog=catalog,
        page=page_plan_from_template(template),
        bindings=extract_bindings(template),
        catalog_sources=("yunprint-live", "template-mining"),
    )


def build_template_domain_plan(
    proposal: TemplatePlanInput,
    context: ReportContext,
    confidence: float,
    assumptions: list[str] | None,
    warnings: list[str] | None,
) -> TemplatePlan:
    """从协议层计划输入构建领域层 TemplatePlan。"""
    style = proposal.table_style
    title_options = proposal.title_options
    return build_plan(
        catalog=context.catalog,
        title=proposal.title,
        master_field_ids=list(proposal.master_field_ids),
        detail_columns=[
            item.model_dump(by_alias=True, exclude_none=True)
            for item in proposal.columns
        ],
        total_field_ids=list(proposal.total_field_ids),
        footer_field_ids=list(proposal.footer_field_ids),
        page=PagePlan(
            paper_name=proposal.page.paper_name,
            orientation=proposal.page.orientation,
            width_cm=proposal.page.width_cm,
            height_cm=proposal.page.height_cm,
            margins_cm=dict(proposal.page.margins_cm),
        ),
        confidence=float(confidence),
        assumptions=list(assumptions or []),
        warnings=list(warnings or []),
        max_rows_per_page=proposal.max_rows_per_page,
        table_name=context.catalog.default_detail_table,
        strategy="quick-table",
        cell_options={
            field_id: options.model_dump(by_alias=True, exclude_none=True)
            for field_id, options in proposal.cell_options.items()
        },
        table_style=TableStylePlan(
            header_height_cm=style.header_height_cm,
            body_height_cm=style.body_height_cm,
            header_font_size=style.header_font_size,
            body_font_size=style.body_font_size,
            outer=BorderPlan(style=style.outer.style, width=style.outer.width),
            inner_horizontal=BorderPlan(
                style=style.inner_horizontal.style,
                width=style.inner_horizontal.width,
            ),
            inner_vertical=BorderPlan(
                style=style.inner_vertical.style,
                width=style.inner_vertical.width,
            ),
        ),
        title_style=TextStylePlan(
            horizontal_align=title_options.horizontal_align or "default",
            vertical_align=title_options.vertical_align or "default",
        ),
    )
