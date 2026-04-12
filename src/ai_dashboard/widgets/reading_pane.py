from __future__ import annotations

from textual.widgets import Static

from rich.text import Text
from rich.console import Group

from ai_dashboard.storage.models import FeedItem


class ReadingPane(Static):
    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, expand=True)
        self._item: FeedItem | None = None

    async def show_item(self, item: FeedItem | None) -> None:
        self._item = item
        self.update(self._render_item(item))

    def _render_item(self, item: FeedItem | None) -> Text | Group:
        if item is None:
            return Text("No item selected.", style="dim")
        if item.source_kind == "arxiv":
            return self._render_arxiv(item)
        if item.source_kind == "hn":
            return self._render_hn(item)
        if item.source_kind == "github_trending":
            return self._render_github_trending(item)
        if item.source_kind == "huggingface":
            return self._render_huggingface(item)
        return self._render_newsletter(item)

    def _render_arxiv(self, item: FeedItem) -> Text | Group:
        payload = item.raw_payload
        lines = [
            "",
            f"Authors: {', '.join(payload.get('authors', []))}",
            f"Category: {payload.get('primary_category', '')}",
            f"arXiv ID: {payload.get('arxiv_id', '')}",
            f"Published: {item.published_at.isoformat()}",
            "",
            "Abstract:",
            payload.get("abstract", "").strip(),
        ]
        return Group(Text(item.title, style="bold"), *[Text(line) for line in lines])

    def _render_hn(self, item: FeedItem) -> Text | Group:
        payload = item.raw_payload
        lines = [
            "",
            f"Points: {payload.get('points')}   Comments: {payload.get('comment_count')}   By: {payload.get('submitted_by')}",
            f"URL: {item.url}",
            "",
            payload.get("text", "") or "(no text)",
        ]
        return Group(Text(item.title, style="bold"), *[Text(line) for line in lines])

    def _render_github_trending(self, item: FeedItem) -> Text | Group:
        payload = item.raw_payload
        lines = [
            "",
            f"⭐ {payload.get('stars')}   Lang: {payload.get('language') or '—'}",
            f"URL: {item.url}",
            "",
            payload.get("description") or "(no description)",
        ]
        return Group(
            Text(f"{payload.get('owner')}/{payload.get('name')}", style="bold"),
            *[Text(line) for line in lines],
        )

    def _render_huggingface(self, item: FeedItem) -> Text | Group:
        payload = item.raw_payload
        lines = [
            "",
            f"Author: {payload.get('author', '—')}",
            f"Pipeline: {payload.get('pipeline_tag', '—')}",
            f"Downloads: {payload.get('downloads', '—')}",
            f"Likes: {payload.get('likes', '—')}",
            f"Tags: {', '.join(payload.get('tags') or [])}",
            "",
            f"URL: {item.url}",
        ]
        return Group(
            Text(
                f"{payload.get('hf_kind', '').upper()}: {payload.get('id', '')}",
                style="bold",
            ),
            *[Text(line) for line in lines],
        )

    def _render_newsletter(self, item: FeedItem) -> Text | Group:
        payload = item.raw_payload
        lines = [
            "",
            f"Publication: {payload.get('publication', '')}",
            f"Published: {item.published_at.isoformat()}",
            f"URL: {item.url}",
            "",
            payload.get("summary", "").strip() or "(no summary)",
        ]
        return Group(Text(item.title, style="bold"), *[Text(line) for line in lines])
