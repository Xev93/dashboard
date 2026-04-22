from __future__ import annotations

from typing import Any

from selectolax.parser import HTMLParser
from textual.widgets import Markdown

from ai_dashboard.content import ContentFetcher
from ai_dashboard.source_catalog import CATALOG_BY_KIND
from ai_dashboard.storage.models import FeedItem


class ReadingPane(Markdown):
    def __init__(
        self,
        *,
        content_fetcher: ContentFetcher | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__("*No item selected.*", id=id)
        self._item: FeedItem | None = None
        self._fetcher = content_fetcher
        self._current_content: str | None = None

    @property
    def current_content(self) -> str | None:
        return self._current_content

    async def show_item(self, item: FeedItem | None) -> None:
        self._item = item
        self._current_content = None
        if item is None:
            await self.update("*No item selected.*")
            return

        markdown = self._render_metadata(item)
        if self._fetcher is not None:
            markdown += "\n\n---\n\n*Loading content...*"
        await self.update(markdown)

        if self._fetcher is not None:
            self.run_worker(self._load_content(item))

    async def _load_content(self, item: FeedItem) -> None:
        if self._fetcher is None:
            return
        content = await self._fetcher.fetch_content(item)
        if self._item != item:
            return
        self._current_content = self._prepare_content(content, item.source_kind)
        markdown = self._render_metadata(item)
        markdown += "\n\n---\n\n"
        markdown += self._current_content
        await self.update(markdown)

    async def show_summary(self, summary: str) -> None:
        """Prepend AI summary above the current content."""
        separator = "\n\n---\n\n"
        header = "## 🤖 AI Summary\n\n"
        current = self._current_content or ""
        combined = f"{header}{summary}{separator}{current}"
        await self.update(combined)

    def _render_metadata(self, item: FeedItem) -> str:
        kind = item.source_kind
        payload = item.raw_payload

        if kind == "arxiv":
            return self._meta_arxiv(item, payload)
        if kind == "hn":
            return self._meta_hn(item, payload)
        if kind == "github_trending":
            return self._meta_github(item, payload)
        if kind == "huggingface":
            return self._meta_hf(item, payload)
        return self._meta_newsletter(item, payload)

    def _meta_arxiv(self, item: FeedItem, payload: dict[str, Any]) -> str:
        authors = ", ".join(payload.get("authors", []))
        return (
            f"# {item.title}\n\n"
            f"**Authors:** {authors}\n\n"
            f"**Category:** {payload.get('primary_category', '')}\n\n"
            f"**arXiv ID:** `{payload.get('arxiv_id', '')}`\n\n"
            f"**Published:** {item.published_at.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"### Abstract\n\n{payload.get('abstract', '').strip()}"
        )

    def _meta_hn(self, item: FeedItem, payload: dict[str, Any]) -> str:
        text = payload.get("text", "")
        return (
            f"# {item.title}\n\n"
            f"**Points:** {payload.get('points', 0)} · "
            f"**Comments:** {payload.get('comment_count', 0)} · "
            f"**By:** {payload.get('submitted_by', '—')}\n\n"
            f"**URL:** {item.url}\n\n" + (f"> {text}\n\n" if text else "")
        )

    def _meta_github(self, item: FeedItem, payload: dict[str, Any]) -> str:
        return (
            f"# {payload.get('owner', '')}/{payload.get('name', '')}\n\n"
            f"⭐ **{payload.get('stars', 0):,}** · "
            f"**Language:** {payload.get('language') or '—'}\n\n"
            f"**URL:** {item.url}\n\n"
            f"{payload.get('description') or ''}"
        )

    def _meta_hf(self, item: FeedItem, payload: dict[str, Any]) -> str:
        downloads = payload.get("downloads")
        downloads_text = (
            f"{downloads:,}" if isinstance(downloads, int) else (downloads or "—")
        )
        return (
            f"# {payload.get('hf_kind', '').upper()}: {payload.get('id', '')}\n\n"
            f"**Author:** {payload.get('author', '—')}\n\n"
            f"**Pipeline:** {payload.get('pipeline_tag', '—')} · "
            f"**Downloads:** {downloads_text} · "
            f"**Likes:** {payload.get('likes', '—')}\n\n"
            f"**Tags:** {', '.join(payload.get('tags') or [])}\n\n"
            f"**URL:** {item.url}"
        )

    def _meta_newsletter(self, item: FeedItem, payload: dict[str, Any]) -> str:
        source = CATALOG_BY_KIND.get(item.source_kind)
        tier = (
            source.tier.replace("_", " ").title()
            if source is not None
            else item.source_kind
        )
        lines = [f"# {item.title}", ""]

        if source is not None:
            lines.extend([f"**Tier:** {tier}", ""])

        if payload.get("publication"):
            lines.extend([f"**Publication:** {payload.get('publication')}", ""])

        authors = payload.get("authors")
        if authors:
            if isinstance(authors, str):
                authors_text = authors
            else:
                authors_text = ", ".join(str(author) for author in authors)
            lines.extend([f"**Authors:** {authors_text}", ""])

        if payload.get("venue"):
            lines.extend([f"**Venue:** {payload.get('venue')}", ""])

        abstract = payload.get("abstract")
        if abstract:
            lines.extend(["### Abstract", "", abstract.strip(), ""])

        summary = payload.get("summary")
        if summary:
            lines.extend(["### Summary", "", summary.strip(), ""])

        available_keys = sorted(payload)
        if available_keys:
            lines.extend(["### Payload", ""])
            for key in available_keys:
                value = payload.get(key)
                if key == "abstract" and abstract:
                    continue
                if key == "summary" and summary:
                    continue
                if key == "authors" and authors:
                    continue
                if key == "publication":
                    continue
                if value in (None, "", [], {}, ()):
                    continue
                if isinstance(value, list):
                    value_text = ", ".join(str(entry) for entry in value)
                else:
                    value_text = str(value)
                lines.append(f"**{key.replace('_', ' ').title()}:** {value_text}")
            lines.append("")

        lines.extend(
            [
                f"**Published:** {item.published_at.strftime('%Y-%m-%d %H:%M UTC')}",
                "",
                f"**URL:** {item.url}",
            ]
        )
        return "\n".join(lines)

    def _prepare_content(self, content: str, source_kind: str) -> str:
        if not content:
            return "*No content available.*"
        if source_kind in ("github_trending", "huggingface"):
            return content
        if "<" in content and ">" in content:
            tree = HTMLParser(content)
            if tree.body:
                return tree.body.text(separator="\n\n", strip=True)
        return content
