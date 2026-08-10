"""字段目录模块：管理字段白名单，提取原生绑定和脱敏 reportData 字段结构。"""

from __future__ import annotations

import json
from importlib import resources
import hashlib
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .domain import DomainError, FieldDefinition


SCOPE_PREFIXES = {"master": "@", "detail": "#", "total": "^"}


class FieldCatalog:
    def __init__(
        self,
        report_name: str,
        report_type: int,
        fields: Sequence[FieldDefinition],
        default_detail_table: str = "明细",
    ):
        self.report_name = report_name
        self.report_type = report_type
        self.fields = sorted(list(fields), key=lambda item: (item.default_order, item.field_id))
        self.default_detail_table = default_detail_table
        self._by_id = {item.field_id: item for item in self.fields}
        if len(self._by_id) != len(self.fields):
            raise DomainError("FIELD_CATALOG_INVALID", "字段目录包含重复 fieldId")

    @classmethod
    def sales_default(cls) -> "FieldCatalog":
        data_path = resources.files("yunprint").joinpath("data/sales_catalog.json")
        with data_path.open("r", encoding="utf-8") as file_obj:
            raw = json.load(file_obj)
        fields = [
            FieldDefinition(
                field_id=item["fieldId"],
                report_name=raw["reportName"],
                report_type=int(raw["reportType"]),
                table_name=item["tableName"],
                scope=item["scope"],
                name=item["name"],
                data_type=item["dataType"],
                aliases=list(item.get("aliases", [])),
                aggregatable=bool(item.get("aggregatable", False)),
                default_recommended=bool(item.get("defaultRecommended", False)),
                default_total=bool(item.get("defaultTotal", False)),
                zone=item.get("zone", "header"),
                default_order=int(item.get("defaultOrder", 0)),
                source=item.get("source", "metadata"),
            )
            for item in raw["fields"]
        ]
        return cls(
            raw["reportName"],
            int(raw["reportType"]),
            fields,
            raw.get("defaultDetailTable", "明细"),
        )

    @classmethod
    def from_native_template(
        cls,
        template: Dict[str, Any],
        report_type: int = 1,
        default_detail_table: str = "明细",
    ) -> "FieldCatalog":
        report_name = str(template.get("ReportName") or "")
        if not report_name:
            raise DomainError("TEMPLATE_INVALID", "模板缺少 ReportName")

        bindings = extract_bindings(template)
        total_names = set(bindings["total"])
        master_zones: Dict[str, str] = {}
        detail_seen = False
        for page in template.get("Pages", []):
            for element in page.get("ReportElements", []) if isinstance(page, dict) else []:
                if not isinstance(element, dict):
                    continue
                for row in element.get("Rows", []):
                    if not isinstance(row, dict):
                        continue
                    texts = [
                        cell.get("CellText")
                        for cell in row.get("Cells", [])
                        if isinstance(cell, dict) and isinstance(cell.get("CellText"), str)
                    ]
                    if any(text.startswith("#") for text in texts):
                        detail_seen = True
                    for text in texts:
                        if text.startswith("@") and text[1:].strip() not in master_zones:
                            master_zones[text[1:].strip()] = "footer" if detail_seen else "header"
        fields: List[FieldDefinition] = []
        order = 0
        for scope in ("master", "detail"):
            for name in bindings[scope]:
                field_id = "%s.%s" % (scope, name)
                order += 10
                inferred_number = name in total_names or any(
                    token in name for token in ("数量", "金额", "单价", "税额", "折扣", "合计")
                )
                fields.append(
                    FieldDefinition(
                        field_id=field_id,
                        report_name=report_name,
                        report_type=report_type,
                        table_name="主表" if scope == "master" else default_detail_table,
                        scope=scope,
                        name=name,
                        data_type="number" if inferred_number else "string",
                        aliases=[],
                        aggregatable=scope == "detail" and name in total_names,
                        default_recommended=True,
                        default_total=scope == "detail" and name in total_names,
                        zone="detail" if scope == "detail" else master_zones.get(name, "header"),
                        default_order=order,
                        source="template-mining",
                    )
                )
        return cls(report_name, report_type, fields, default_detail_table)

    def get(self, field_id: str) -> FieldDefinition:
        try:
            return self._by_id[field_id]
        except KeyError as exc:
            raise DomainError("FIELD_NOT_FOUND", "字段目录中不存在：%s" % field_id) from exc

    def default_fields(self, scope: str, zone: Optional[str] = None) -> List[FieldDefinition]:
        return [
            item
            for item in self.fields
            if item.scope == scope
            and item.default_recommended
            and (zone is None or item.zone == zone)
        ]

    def model_payload(self) -> List[Dict[str, Any]]:
        return [item.to_model_dict() for item in self.fields]

    def catalog_hash(self) -> str:
        payload = {
            "reportName": self.report_name,
            "reportType": self.report_type,
            "defaultDetailTable": self.default_detail_table,
            "fields": self.model_payload(),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_report_data(
        cls,
        report_data: Dict[str, Any],
        native_report_name: str,
        report_type: int = 1,
    ) -> "FieldCatalog":
        """只提取 reportData 字段结构；明确忽略主表值和所有明细数据行。"""
        if not isinstance(report_data, dict):
            raise DomainError("REPORT_DATA_INVALID", "reportData 顶层必须是对象")
        grid_list = report_data.get("gridList", [])
        if not isinstance(grid_list, list):
            raise DomainError("REPORT_DATA_INVALID", "reportData.gridList 必须是数组")
        active_grids = [item for item in grid_list if isinstance(item, dict) and item.get("detailFields")]
        if len(active_grids) > 1:
            raise DomainError("MULTI_DETAIL_UNSUPPORTED", "当前控制台只支持一个明细表")
        detail_table = str(active_grids[0].get("detailName") or "明细") if active_grids else "明细"
        fields: List[FieldDefinition] = []
        seen = set()
        order = 0

        master_fields = report_data.get("masterFields", [])
        if not isinstance(master_fields, list):
            raise DomainError("REPORT_DATA_INVALID", "reportData.masterFields 必须是数组")
        for item in master_fields:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("dataField") or "").strip()
            if not name:
                continue
            field_id = "master.%s" % name
            if field_id in seen:
                continue
            seen.add(field_id)
            order += 10
            data_type = _normalize_report_data_type(item.get("columnType") or item.get("dataType"))
            fields.append(
                FieldDefinition(
                    field_id=field_id,
                    report_name=native_report_name,
                    report_type=report_type,
                    table_name="主表",
                    scope="master",
                    name=name,
                    data_type=data_type,
                    aliases=[],
                    aggregatable=False,
                    default_recommended=False,
                    default_total=False,
                    zone="header",
                    default_order=order,
                    source="report-data",
                )
            )

        if active_grids:
            detail_fields = active_grids[0].get("detailFields", [])
            if not isinstance(detail_fields, list):
                raise DomainError("REPORT_DATA_INVALID", "detailFields 必须是数组")
            for item in detail_fields:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("dataField") or "").strip()
                if not name:
                    continue
                field_id = "detail.%s" % name
                if field_id in seen:
                    continue
                seen.add(field_id)
                order += 10
                data_type = _normalize_report_data_type(item.get("columnType") or item.get("dataType"))
                fields.append(
                    FieldDefinition(
                        field_id=field_id,
                        report_name=native_report_name,
                        report_type=report_type,
                        table_name=detail_table,
                        scope="detail",
                        name=name,
                        data_type=data_type,
                        aliases=[],
                        aggregatable=data_type == "number",
                        default_recommended=False,
                        default_total=False,
                        zone="detail",
                        default_order=order,
                        source="report-data",
                    )
                )
        if not fields:
            raise DomainError("REPORT_DATA_INVALID", "reportData 中没有可用字段结构")
        return cls(native_report_name, report_type, fields, detail_table)

    @classmethod
    def merge(cls, template_catalog: "FieldCatalog", authority_catalog: "FieldCatalog") -> "FieldCatalog":
        """模板统计提供默认布局，reportData 等权威来源补齐字段并覆盖类型。"""
        if template_catalog.report_type != authority_catalog.report_type:
            raise DomainError("CATALOG_CONFLICT", "字段目录 reportType 不一致")
        template_by_id = {item.field_id: item for item in template_catalog.fields}
        authority_by_id = {item.field_id: item for item in authority_catalog.fields}
        result: List[FieldDefinition] = []
        max_order = max((item.default_order for item in template_catalog.fields), default=0)
        ordered_ids = [item.field_id for item in template_catalog.fields]
        ordered_ids.extend(item.field_id for item in authority_catalog.fields if item.field_id not in template_by_id)
        for field_id in ordered_ids:
            base = template_by_id.get(field_id)
            authority = authority_by_id.get(field_id)
            if base and authority:
                result.append(
                    FieldDefinition(
                        field_id=field_id,
                        report_name=template_catalog.report_name,
                        report_type=template_catalog.report_type,
                        table_name=authority.table_name if authority.scope == "detail" else base.table_name,
                        scope=base.scope,
                        name=base.name,
                        data_type=authority.data_type if authority.data_type != "unknown" else base.data_type,
                        aliases=sorted(set(base.aliases + authority.aliases)),
                        aggregatable=base.aggregatable or authority.aggregatable,
                        default_recommended=base.default_recommended,
                        default_total=base.default_total,
                        zone=base.zone,
                        default_order=base.default_order,
                        source="template-mining+report-data",
                    )
                )
            elif base:
                result.append(base)
            elif authority:
                max_order += 10
                result.append(
                    FieldDefinition(
                        field_id=authority.field_id,
                        report_name=template_catalog.report_name,
                        report_type=template_catalog.report_type,
                        table_name=authority.table_name,
                        scope=authority.scope,
                        name=authority.name,
                        data_type=authority.data_type,
                        aliases=authority.aliases,
                        aggregatable=authority.aggregatable,
                        default_recommended=False,
                        default_total=False,
                        zone=authority.zone,
                        default_order=max_order,
                        source=authority.source,
                    )
                )
        return cls(
            template_catalog.report_name,
            template_catalog.report_type,
            result,
            authority_catalog.default_detail_table or template_catalog.default_detail_table,
        )


def _walk(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def extract_bindings(template: Dict[str, Any]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {"master": [], "detail": [], "total": []}
    reverse = {"@": "master", "#": "detail", "^": "total"}
    for node in _walk(template):
        cell_text = node.get("CellText") if isinstance(node, dict) else None
        if not isinstance(cell_text, str) or not cell_text:
            continue
        scope = reverse.get(cell_text[0])
        if not scope:
            continue
        name = cell_text[1:].strip()
        if name and name not in result[scope]:
            result[scope].append(name)
    return result


def _normalize_report_data_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"number", "decimal", "money", "float", "double", "integer", "int"}:
        return "number"
    if normalized in {"date"}:
        return "date"
    if normalized in {"datetime", "timestamp"}:
        return "datetime"
    if normalized in {"boolean", "bool"}:
        return "boolean"
    if normalized in {"image", "picture"}:
        return "image"
    if normalized in {"string", "text", "varchar", "char"}:
        return "string"
    return "unknown"
