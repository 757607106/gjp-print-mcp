import json

from yunprint.catalog import FieldCatalog, extract_bindings


def test_sales_catalog_matches_observed_bindings():
    catalog = FieldCatalog.sales_default()
    assert catalog.report_name == "销售单"
    assert len(catalog.default_fields("master", "header")) == 6
    assert len(catalog.default_fields("master", "footer")) == 5
    assert len(catalog.default_fields("detail")) == 8
    assert catalog.get("detail.数量").aggregatable is True
    assert catalog.get("detail.金额").default_total is True


def test_extract_bindings_is_stable_and_deduplicated():
    template = {
        "ReportName": "销售单",
        "Pages": [
            {
                "ReportElements": [
                    {
                        "Rows": [
                            {"Cells": [{"CellText": "@购买单位"}, {"CellText": "@购买单位"}]},
                            {"Cells": [{"CellText": "#数量"}, {"CellText": "^数量"}]},
                        ]
                    }
                ]
            }
        ],
    }
    assert extract_bindings(template) == {
        "master": ["购买单位"],
        "detail": ["数量"],
        "total": ["数量"],
    }


def test_reverse_catalog_infers_footer_and_totals():
    template = {
        "ReportName": "销售单",
        "Pages": [
            {
                "ReportElements": [
                    {
                        "Rows": [
                            {"Cells": [{"CellText": "@购买单位"}]},
                            {"Cells": [{"CellText": "#数量"}]},
                            {"Cells": [{"CellText": "^数量"}]},
                            {"Cells": [{"CellText": "@制单人"}]},
                        ]
                    }
                ]
            }
        ],
    }
    catalog = FieldCatalog.from_native_template(template, default_detail_table="销售明细")
    assert catalog.get("master.购买单位").zone == "header"
    assert catalog.get("master.制单人").zone == "footer"
    assert catalog.get("detail.数量").aggregatable is True
    assert catalog.get("detail.数量").default_total is True
