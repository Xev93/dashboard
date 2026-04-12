"""Source tabs widget — horizontal tab bar above the feed list."""

from __future__ import annotations

from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class SourceTabs(Static):
    class TabChanged(Message):
        def __init__(self, source_kind: str | None) -> None:
            super().__init__()
            self.source_kind = source_kind

    TABS = [
        ("All", None),
        ("AX", "arxiv"),
        ("HN", "hn"),
        ("GH", "github_trending"),
        ("HF", "huggingface"),
        ("NL", "newsletter"),
        ("RD", "reddit"),
        ("LB", "lab_blog"),
        ("PW", "papers_with_code"),
    ]

    active_index: reactive[int] = reactive(0)

    def render(self) -> str:
        parts: list[str] = []
        for i, (label, _) in enumerate(self.TABS):
            if i == self.active_index:
                parts.append(f"[bold reverse] {label} [/]")
            else:
                parts.append(f" {label} ")
        return " ".join(parts)

    def select_tab(self, index: int) -> None:
        if 0 <= index < len(self.TABS):
            self.active_index = index
            _, source_kind = self.TABS[index]
            self.post_message(self.TabChanged(source_kind))

    def _select(self, index: int) -> None:
        self.select_tab(index)
