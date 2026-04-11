from __future__ import annotations

from pathlib import Path

PRODUCTION_TARGETS = [
    "src/ai_dashboard/app.py",
    "src/ai_dashboard/workers.py",
    "src/ai_dashboard/widgets",
    "src/ai_dashboard/strategies",
    "src/ai_dashboard/sources/__init__.py",
    "src/ai_dashboard/sources/arxiv.py",
    "src/ai_dashboard/sources/hackernews.py",
    "src/ai_dashboard/sources/github_trending.py",
    "src/ai_dashboard/sources/huggingface.py",
    "src/ai_dashboard/sources/newsletter.py",
]

FORBIDDEN_TOKENS = ("NullAdapter", "sources._null", "sources/_null")


def _production_files() -> list[Path]:
    files: list[Path] = []
    for target in PRODUCTION_TARGETS:
        p = Path(target)
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(p.rglob("*.py"))
    return files


def test_null_adapter_is_not_referenced_by_production_code() -> None:
    violations: list[str] = []
    for f in _production_files():
        content = f.read_text()
        for token in FORBIDDEN_TOKENS:
            if token in content:
                violations.append(f"{f}: contains forbidden token {token!r}")
    assert not violations, (
        "Production code references NullAdapter (bootstrap-only):\n  "
        + "\n  ".join(violations)
    )
