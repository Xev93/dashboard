from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import cast

import httpx

from ai_dashboard.storage.models import FeedItem

DEFAULT_VENUES = ["NeurIPS", "ICML", "CVPR", "ICLR", "AAAI"]
USER_AGENT = "ai-dashboard/0.2 (research feed reader)"

logger = logging.getLogger(__name__)


class DblpAdapter:
    kind: str = "dblp"
    source_kind: str = "dblp"
    default_interval_seconds: int = 3600

    def __init__(self, http: httpx.AsyncClient, options: dict[str, object]) -> None:
        self._http: httpx.AsyncClient = http
        options_dict = options

        venues = options_dict.get("venues", DEFAULT_VENUES)
        if isinstance(venues, list):
            self._venues: list[str] = [
                venue for venue in cast(list[object], venues) if isinstance(venue, str)
            ]
        else:
            self._venues = list(DEFAULT_VENUES)
        if not self._venues:
            self._venues = list(DEFAULT_VENUES)

        year = options_dict.get("year", datetime.now(timezone.utc).year)
        self._year: int = self._parse_year(year)

    async def fetch(self) -> list[FeedItem]:
        items: list[FeedItem] = []

        for venue in self._venues:
            try:
                response = await self._http.get(
                    "https://dblp.org/search/publ/api",
                    params={
                        "q": f"venue:{venue}",
                        "h": 25,
                        "format": "json",
                    },
                    headers={"User-Agent": USER_AGENT},
                )
                _ = response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("[dblp] failed to fetch venue %s: %s", venue, exc)
                continue

            try:
                payload = cast(object, response.json())
            except ValueError as exc:
                logger.warning("[dblp] invalid payload for venue %s: %s", venue, exc)
                continue

            hits = self._extract_hits(payload, venue)
            if hits is None:
                continue

            for hit in hits:
                item = self._build_feed_item(hit, venue)
                if item is not None:
                    items.append(item)

        return items

    def _parse_year(self, year: object) -> int:
        if isinstance(year, int):
            return year
        if isinstance(year, str):
            try:
                return int(year)
            except ValueError:
                pass
        return datetime.now(timezone.utc).year

    def _extract_hits(
        self, payload: object, venue: str
    ) -> list[dict[str, object]] | None:
        if not isinstance(payload, dict):
            logger.warning(
                "[dblp] invalid payload for venue %s: root is not an object", venue
            )
            return None
        payload_dict = cast(dict[str, object], payload)

        result = payload_dict.get("result")
        if not isinstance(result, dict):
            logger.warning("[dblp] invalid payload for venue %s: missing result", venue)
            return None
        result_dict = cast(dict[str, object], result)

        hits = result_dict.get("hits")
        if not isinstance(hits, dict):
            logger.warning("[dblp] invalid payload for venue %s: missing hits", venue)
            return None
        hits_dict = cast(dict[str, object], hits)

        hit_list = hits_dict.get("hit")
        if hit_list is None:
            return []  # 0 results — valid response, just empty
        if not isinstance(hit_list, list):
            logger.warning(
                "[dblp] invalid payload for venue %s: unexpected hit type", venue
            )
            return None

        return [hit for hit in cast(list[object], hit_list) if isinstance(hit, dict)]

    def _build_feed_item(self, hit: dict[str, object], venue: str) -> FeedItem | None:
        info = hit.get("info")
        if not isinstance(info, dict):
            return None
        info_dict = cast(dict[str, object], info)

        title = info_dict.get("title")
        if not isinstance(title, str) or not title:
            return None

        url = self._get_str(info_dict, "ee") or self._get_str(info_dict, "url")

        dblp_key = self._get_str(info_dict, "key")

        doi = self._get_str(info_dict, "doi")

        authors = self._extract_authors(info_dict.get("authors"))

        item_year = self._parse_year(info_dict.get("year", self._year))

        return FeedItem(
            id=None,
            source_kind="dblp",
            source_uid=f"dblp_{dblp_key}",
            title=title,
            url=url,
            published_at=datetime(item_year, 7, 1, tzinfo=timezone.utc),
            raw_payload={
                "venue": venue,
                "authors": authors,
                "doi": doi,
                "dblp_key": dblp_key,
            },
        )

    def _extract_authors(self, authors: object) -> list[str]:
        if not isinstance(authors, dict):
            return []
        authors_dict = cast(dict[str, object], authors)

        author_list = authors_dict.get("author")
        if isinstance(author_list, list):
            names: list[str] = []
            for author in cast(list[object], author_list):
                if isinstance(author, str):
                    names.append(author)
                    continue
                if isinstance(author, dict):
                    author_dict = cast(dict[str, object], author)
                    text = author_dict.get("text")
                    if isinstance(text, str):
                        names.append(text)
            return names

        if isinstance(author_list, str):
            return [author_list]
        if isinstance(author_list, dict):
            author_dict = cast(dict[str, object], author_list)
            text = author_dict.get("text")
            if isinstance(text, str):
                return [text]

        return []

    def _get_str(self, payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        return value if isinstance(value, str) else ""
