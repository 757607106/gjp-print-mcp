"""标准纸张模块：把 A4/A5 等自然语言要求确定性映射为纸张尺寸，避免依赖模型记忆。"""

from __future__ import annotations

import logging
import re
from typing import Dict, Tuple

from .domain import TemplatePlan


logger = logging.getLogger(__name__)

STANDARD_PAPERS_CM: Dict[str, Tuple[float, float]] = {
    "A3": (29.7, 42.0),
    "A4": (21.0, 29.7),
    "A5": (14.8, 21.0),
}


def apply_standard_paper_requirements(message: str, plan: TemplatePlan) -> None:
    matches = list(re.finditer(r"(?<![A-Z0-9])(A3|A4|A5)(?![A-Z0-9])", message.upper()))
    if not matches:
        return
    paper_name = matches[-1].group(1)
    last_landscape = message.rfind("横向")
    last_portrait = message.rfind("纵向")
    if max(last_landscape, last_portrait) >= 0:
        plan.page.orientation = "landscape" if last_landscape > last_portrait else "portrait"
    width, height = STANDARD_PAPERS_CM[paper_name]
    if plan.page.orientation == "landscape":
        width, height = height, width
    plan.page.paper_name = paper_name
    plan.page.width_cm = width
    plan.page.height_cm = height
    logger.info(
        "标准纸张规则已应用 paper=%s orientation=%s width_cm=%s height_cm=%s",
        paper_name,
        plan.page.orientation,
        width,
        height,
    )
