from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import cast

import httpx

from ai_dashboard.storage.models import FeedItem

DEFAULT_VENUES = ["NeurIPS.cc/2025/Conference", "ICLR.cc/2025/Conference"]
USER_AGENT = "ai-dashboard/0.2 (research feed reader)"

logger = logging.getLogger(__name__)


class OpenReviewAdapter:
    kind: str = "openreview"
    source_kind: str = "openreview"
    default_interval_seconds: int = 1800

    def __init__(self, http: httpx.AsyncClient, options: dict[str, object]) -> None:
        self._http: httpx.AsyncClient = http
        options_dict = options
        self._venues: list[str]

        venues = options_dict.get("venues", DEFAULT_VENUES)
        if isinstance(venues, list):
            self._venues = [
                venue for venue in cast(list[object], venues) if isinstance(venue, str)
            ]
        else:
            self._venues = list(DEFAULT_VENUES)
        if not self._venues:
            self._venues = list(DEFAULT_VENUES)

        status = options_dict.get("status")
        self._status: str | None = status if isinstance(status, str) else None

    async def fetch(self) -> list[FeedItem]:
        items: list[FeedItem] = []

        for venue_id in self._venues:
            try:
                response = await self._http.get(
                    "https://api2.openreview.net/notes",
                    params={
                        "invitation": f"{venue_id}/-/Submission",
                        "limit": 25,
                        "sort": "cdate:desc",
                    },
                    headers={"User-Agent": USER_AGENT},
                )
                _ = response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning(
                    "[openreview] failed to fetch venue %s: %s", venue_id, exc
                )
                continue

            try:
                payload = cast(object, response.json())
            except ValueError as exc:
                logger.warning(
                    "[openreview] invalid payload for venue %s: %s", venue_id, exc
                )
                continue

            if not isinstance(payload, dict):
                logger.warning(
                    "[openreview] invalid payload for venue %s: root is not an object",
                    venue_id,
                )
                continue

            payload_dict = cast(dict[str, object], payload)
            notes = payload_dict.get("notes")
            if not isinstance(notes, list):
                logger.warning(
                    "[openreview] invalid payload for venue %s: missing notes list",
                    venue_id,
                )
                continue

            notes_list = cast(list[object], notes)
            for note_obj in notes_list:
                if not isinstance(note_obj, dict):
                    continue
                item = self._build_feed_item(
                    cast(dict[str, object], note_obj), venue_id
                )
                if item is not None:
                    items.append(item)

        return items

    def _build_feed_item(
        self, note: dict[str, object], venue_id: str
    ) -> FeedItem | None:
        note_id = note.get("id")
        cdate = note.get("cdate")
        content = note.get("content")

        if not isinstance(note_id, str):
            return None
        if not isinstance(cdate, (int, float)):
            return None
        if not isinstance(content, dict):
            return None

        content_dict = cast(dict[str, object], content)
        title = self._content_value(content_dict, "title")
        if not isinstance(title, str) or not title:
            return None

        if self._should_filter_out(note, content_dict):
            return None

        abstract = self._content_value(content_dict, "abstract")
        if not isinstance(abstract, str):
            abstract = ""

        authors = self._content_value(content_dict, "authors")
        author_list: list[str] = []
        if isinstance(authors, list):
            author_list = [
                author
                for author in cast(list[object], authors)
                if isinstance(author, str)
            ]

        return FeedItem(
            id=None,
            source_kind=self.source_kind,
            source_uid=f"or_{note_id}",
            title=title,
            url=f"https://openreview.net/forum?id={note_id}",
            published_at=datetime.fromtimestamp(float(cdate) / 1000, tz=timezone.utc),
            raw_payload={
                "abstract": abstract[:500],
                "venue": venue_id,
                "authors": author_list,
            },
        )

    def _should_filter_out(
        self, note: dict[str, object], content: dict[str, object]
    ) -> bool:
        if self._status is None:
            return False

        normalized_status = self._status.strip().lower()
        if normalized_status not in {
            "accepted",
            "accept",
            "accept-only",
            "accepted-only",
        }:
            return False

        return not self._is_accepted(note, content)

    def _is_accepted(self, note: dict[str, object], content: dict[str, object]) -> bool:
        candidates = [
            self._content_value(content, "venue"),
            self._content_value(content, "status"),
            self._content_value(content, "decision"),
            note.get("venue"),
        ]

        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            normalized = candidate.strip().lower()
            if "accept" in normalized and "reject" not in normalized:
                return True

        return False

    def _content_value(self, content: dict[str, object], key: str) -> object:
        field = content.get(key)
        if not isinstance(field, dict):
            return None
        field_dict = cast(dict[str, object], field)
        return field_dict.get("value")
