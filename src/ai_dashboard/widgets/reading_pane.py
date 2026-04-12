from __future__ import annotations

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import Static

from ai_dashboard.content import ContentFetcher
from ai_dashboard.storage.models import FeedItem


class ReadingPane(Static):
    def __init__(
        self,
        *,
        content_fetcher: ContentFetcher | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id, expand=True)
        self._item: FeedItem | None = None
        self._fetcher = content_fetcher

    async def show_item(self, item: FeedItem | None) -> None:
        self._item = item
        self.update(self._render_item(item))
        if item is not None and self._fetcher is not None:
            self.run_worker(self._load_content(item))

    async def _load_content(self, item: FeedItem) -> None:
        if self._fetcher is None:
            return
        content = await self._fetcher.fetch_content(item)
        if self._item != item:
            return
        self.update(self._render_item(item, content))

    def _render_item(
        self, item: FeedItem | None, content: str | None = None
    ) -> Text | Group | Markdown:
        if item is None:
            return Text("No item selected.", style="dim")
        if item.source_kind == "arxiv":
            return self._render_arxiv(item, content)
        if item.source_kind == "hn":
            return self._render_hn(item, content)
        if item.source_kind == "github_trending":
            return self._render_github_trending(item, content)
        if item.source_kind == "huggingface":
            return self._render_huggingface(item, content)
        return self._render_newsletter(item, content)

    def _render_arxiv(
        self, item: FeedItem, content: str | None = None
    ) -> Text | Group | Markdown:
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
        return self._group_with_content(item.title, lines, content, item.source_kind)

    def _render_hn(
        self, item: FeedItem, content: str | None = None
    ) -> Text | Group | Markdown:
        payload = item.raw_payload
        lines = [
            "",
            f"Points: {payload.get('points')}   Comments: {payload.get('comment_count')}   By: {payload.get('submitted_by')}",
            f"URL: {item.url}",
            "",
            payload.get("text", "") or "(no text)",
        ]
        return self._group_with_content(item.title, lines, content, item.source_kind)

    def _render_github_trending(
        self, item: FeedItem, content: str | None = None
    ) -> Text | Group | Markdown:
        payload = item.raw_payload
        lines = [
            "",
            f"⭐ {payload.get('stars')}   Lang: {payload.get('language') or '—'}",
            f"URL: {item.url}",
            "",
            payload.get("description") or "(no description)",
        ]
        return self._group_with_content(
            f"{payload.get('owner')}/{payload.get('name')}",
            lines,
            content,
            item.source_kind,
        )

    def _render_huggingface(
        self, item: FeedItem, content: str | None = None
    ) -> Text | Group | Markdown:
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
        return self._group_with_content(
            f"{payload.get('hf_kind', '').upper()}: {payload.get('id', '')}",
            lines,
            content,
            item.source_kind,
        )

    def _render_newsletter(
        self, item: FeedItem, content: str | None = None
    ) -> Text | Group | Markdown:
        payload = item.raw_payload
        lines = [
            "",
            f"Publication: {payload.get('publication', '')}",
            f"Published: {item.published_at.isoformat()}",
            f"URL: {item.url}",
            "",
            payload.get("summary", "").strip() or "(no summary)",
        ]
        return self._group_with_content(item.title, lines, content, item.source_kind)

    def _strip_html(self, text: str) -> str:
        if "<" not in text:
            return text
        from selectolax.parser import HTMLParser

        tree = HTMLParser(text)
        return tree.body.text(separator="\n", strip=True) if tree.body else text

    def _group_with_content(
        self,
        title: str,
        lines: list[str],
        content: str | None,
        source_kind: str = "",
    ) -> Group:
        renderables = [Text(title, style="bold"), *[Text(line) for line in lines]]
        if content is None:
            if self._fetcher is not None:
                renderables.extend(
                    [
                        Text(""),
                        Text("─" * 40, style="dim"),
                        Text("Loading content...", style="dim"),
                    ]
                )
        else:
            renderables.append(Text(""))
            renderables.append(Text("─" * 40, style="dim"))
            if source_kind in ("github_trending", "huggingface"):
                renderables.append(Markdown(content))
            else:
                cleaned = self._strip_html(content)
                renderables.append(Text(cleaned))
        return Group(*renderables)
