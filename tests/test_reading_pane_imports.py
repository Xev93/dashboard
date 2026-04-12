from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_RICH_IMPORTS = {
    "rich.markdown",
    "rich.syntax",
    "rich.table",
    "rich.tree",
    "rich.pretty",
    "rich.traceback",
}


def test_reading_pane_does_not_import_rich_rendering_complexity() -> None:
    src_path = Path("src/ai_dashboard/widgets/reading_pane.py")
    src = src_path.read_text()
    tree = ast.parse(src, filename=str(src_path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in FORBIDDEN_RICH_IMPORTS:
                violations.append(f"line {node.lineno}: from {mod} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_RICH_IMPORTS:
                    violations.append(f"line {node.lineno}: import {alias.name}")
    assert not violations, (
        "reading_pane.py imports forbidden rich rendering modules:\n  "
        + "\n  ".join(violations)
    )
