"""报表上下文模块：维护线上模板导入后的字段目录、页面信息和字段结构合并。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Tuple

from .catalog import FieldCatalog, extract_bindings
from .domain import DomainError, PagePlan
from .native import PX_PER_CM


logger = logging.getLogger(__name__)
STANDARD_PAPER_CM = {
    "A3": (29.7, 42.0),
    "A4": (21.0, 29.7),
    "A5": (14.8, 21.0),
}


@dataclass(frozen=True)
class ReportProfile:
    """不可变报表定义；描述已从线上导入的业务报表。"""

    slug: str
    logical_name: str
    native_report_name: str
    aliases: Tuple[str, ...]
    detail_table: str


@dataclass
class ReportContext:
    """一次会话绑定的真实报表上下文，完整模板只留在确定性程序内。"""

    profile: ReportProfile
    base_template: Dict[str, Any]
    base_hash: str
    catalog: FieldCatalog
    page: PagePlan
    bindings: Dict[str, List[str]]
    catalog_sources: Tuple[str, ...] = ("template-mining",)

    def planner_payload(self) -> Dict[str, Any]:
        return {
            "logicalReportName": self.profile.logical_name,
            "nativeReportName": self.profile.native_report_name,
            "baseTemplateHash": self.base_hash,
            "basePageCount": len(self.base_template.get("Pages", [])),
            "basePage": {
                "paperName": self.page.paper_name,
                "orientation": self.page.orientation,
                "widthCm": self.page.width_cm,
                "heightCm": self.page.height_cm,
                "marginsCm": self.page.margins_cm,
            },
            "baseBindings": self.bindings,
            "catalogHash": self.catalog.catalog_hash(),
            "catalogSources": list(self.catalog_sources),
            "capabilities": ["clone-base-attributes", "quick-table-structure"],
            "unsupportedOperations": [
                "multi-detail-table",
                "free-drawing",
                "chart-generation",
                "arbitrary-expression",
            ],
        }


def merge_report_data(context: ReportContext, report_data: Dict[str, Any]) -> ReportContext:
    """将脱敏字段结构合入当前线上模板目录；原始字段值和明细行不会保存到上下文。"""
    declared_name = str(report_data.get("reportName") or "").strip()
    valid_names = {context.profile.logical_name, context.profile.native_report_name}
    if declared_name and declared_name not in valid_names:
        raise DomainError(
            "CATALOG_CONFLICT",
            "reportData 报表 %s 与当前会话 %s 不一致" % (declared_name, context.profile.logical_name),
        )
    authority = FieldCatalog.from_report_data(
        report_data,
        native_report_name=context.profile.native_report_name,
        report_type=context.catalog.report_type,
    )
    merged = FieldCatalog.merge(context.catalog, authority)
    logger.info(
        "reportData 字段结构已脱敏合并 report=%s fields_before=%d fields_after=%d values_removed=true catalog_hash=%s",
        context.profile.logical_name,
        len(context.catalog.fields),
        len(merged.fields),
        merged.catalog_hash(),
    )
    return ReportContext(
        profile=context.profile,
        base_template=deepcopy(context.base_template),
        base_hash=context.base_hash,
        catalog=merged,
        page=context.page,
        bindings=deepcopy(context.bindings),
        catalog_sources=("yunprint-live", "template-mining", "report-data"),
    )


def page_plan_from_template(template: Dict[str, Any]) -> PagePlan:
    return _page_plan_from_template(template)


def _page_plan_from_template(template: Dict[str, Any]) -> PagePlan:
    setting = template.get("PageSetting") if isinstance(template.get("PageSetting"), dict) else {}
    pages = template.get("Pages") if isinstance(template.get("Pages"), list) else []
    first_page = pages[0] if pages and isinstance(pages[0], dict) else {}
    paper_name = str(setting.get("PaperName") or "自定义纸张")
    orientation = "landscape" if setting.get("PaperOrientation") == 1 else "portrait"
    width = _centimeters(setting.get("PaperWidthUM"))
    height = _centimeters(setting.get("PaperHeightUM"))
    standard_width, standard_height = STANDARD_PAPER_CM.get(paper_name.upper(), (21.0, 29.7))
    width = width or _pixels_to_centimeters(first_page.get("Width")) or standard_width
    height = height or _pixels_to_centimeters(first_page.get("Height")) or standard_height
    if paper_name.upper() in STANDARD_PAPER_CM:
        if orientation == "landscape" and width < height:
            width, height = height, width
        if orientation == "portrait" and width > height:
            width, height = height, width
    margins = {
        "top": _centimeters(setting.get("TopMarginUM")) or 0.0,
        "right": _centimeters(setting.get("RightMarginUM")) or 0.0,
        "bottom": _centimeters(setting.get("BottomMarginUM")) or 0.0,
        "left": _centimeters(setting.get("LeftMarginUM")) or 0.0,
    }
    return PagePlan(
        paper_name=paper_name,
        orientation=orientation,
        width_cm=width,
        height_cm=height,
        margins_cm=margins,
    )


def _centimeters(value: Any) -> Optional[float]:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return round(float(value) / 100.0, 3)


def _pixels_to_centimeters(value: Any) -> Optional[float]:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return round(float(value) / PX_PER_CM, 1)
