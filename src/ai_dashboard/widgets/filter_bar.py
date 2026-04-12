"""Text filter bar — appears when '/' is pressed."""

from __future__ import annotations

from typing import Any

from textual.message import Message
from textual.widgets import Input


class FilterBar(Input):
    class FilterChanged(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class FilterClosed(Message):
        pass

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(placeholder="Type to filter...", **kwargs)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.post_message(self.FilterChanged(text=event.value))

    async def key_escape(self) -> None:
        self.value = ""
        self.post_message(self.FilterClosed())
