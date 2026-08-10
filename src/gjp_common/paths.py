"""路径模块：发现项目根目录，让运行时相对路径不受当前工作目录影响。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

from .errors import DomainError


PathValue = Union[str, Path]


def _is_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").is_file() and (path / "src" / "gjp_common").is_dir()


def discover_project_root(start: Optional[PathValue] = None) -> Path:
    explicit = os.getenv("GJP_PROJECT_ROOT")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not _is_project_root(root):
            raise DomainError("PROJECT_ROOT_INVALID", "GJP_PROJECT_ROOT 不是有效项目根目录：%s" % root)
        return root

    current = Path(start).expanduser().resolve() if start is not None else Path.cwd().resolve()
    search = [current] + list(current.parents)
    package_root = Path(__file__).resolve().parents[2]
    if package_root not in search:
        search.append(package_root)
    for candidate in search:
        if _is_project_root(candidate):
            return candidate
    raise DomainError(
        "PROJECT_ROOT_NOT_FOUND",
        "无法定位项目根目录；请设置 GJP_PROJECT_ROOT",
    )
