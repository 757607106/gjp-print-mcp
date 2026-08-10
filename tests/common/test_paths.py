from gjp_common.paths import discover_project_root


def _project(tmp_path):
    root = tmp_path / "project"
    (root / "src" / "gjp_common").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    return root


def test_project_root_is_discovered_from_nested_docs_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("GJP_PROJECT_ROOT", raising=False)
    root = _project(tmp_path)

    assert discover_project_root(root / "docs") == root
