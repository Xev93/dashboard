from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, cast

import httpx

from ai_dashboard.storage.models import FeedItem

DEFAULT_SUBREDDITS = ["MachineLearning", "artificial", "LocalLLaMA"]
USER_AGENT = "ai-dashboard/0.2 (personal feed reader)"

logger = logging.getLogger(__name__)


class RedditAdapter:
    kind: str = "reddit"
    source_kind: str = "reddit"
    default_interval_seconds: int = 300

    def __init__(self, http: httpx.AsyncClient, options: dict[str, Any]) -> None:
        self._http: httpx.AsyncClient = http
        options_dict = cast(dict[str, object], options)
        subreddits = options_dict.get("subreddits", DEFAULT_SUBREDDITS)
        if isinstance(subreddits, list):
            self._subreddits: list[str] = [
                subreddit
                for subreddit in cast(list[object], subreddits)
                if isinstance(subreddit, str)
            ]
        else:
            self._subreddits = list(DEFAULT_SUBREDDITS)
        if not self._subreddits:
            self._subreddits = list(DEFAULT_SUBREDDITS)

    async def fetch(self) -> list[FeedItem]:
        items: list[FeedItem] = []

        for subreddit in self._subreddits:
            try:
                response = await self._http.get(
                    f"https://www.reddit.com/r/{subreddit}/hot.json?limit=25",
                    headers={"User-Agent": USER_AGENT},
                )
                if response.status_code == 429:
                    logger.warning("[reddit] rate limited for r/%s", subreddit)
                    continue
                _ = response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("[reddit] failed to fetch r/%s: %s", subreddit, exc)
                continue

            try:
                payload = cast(object, response.json())
            except ValueError as exc:
                logger.warning("[reddit] invalid payload for r/%s: %s", subreddit, exc)
                continue

            if not isinstance(payload, dict):
                logger.warning(
                    "[reddit] invalid payload for r/%s: root is not an object",
                    subreddit,
                )
                continue
            payload_dict = cast(dict[str, object], payload)

            data = payload_dict.get("data")
            if not isinstance(data, dict):
                logger.warning(
                    "[reddit] invalid payload for r/%s: missing data object", subreddit
                )
                continue
            data_dict = cast(dict[str, object], data)

            children = data_dict.get("children")
            if not isinstance(children, list):
                logger.warning(
                    "[reddit] invalid payload for r/%s: missing children list",
                    subreddit,
                )
                continue

            for child in cast(list[object], children):
                if not isinstance(child, dict):
                    continue
                child_dict = cast(dict[str, object], child)
                post = child_dict.get("data")
                if not isinstance(post, dict):
                    continue
                item = self._build_feed_item(cast(dict[str, object], post))
                if item is not None:
                    items.append(item)

        return items

    def _build_feed_item(self, post: dict[str, object]) -> FeedItem | None:
        name = post.get("name")
        title_obj = post.get("title")
        permalink = post.get("permalink")
        created_utc_obj = post.get("created_utc")

        if not isinstance(name, str):
            return None
        if not isinstance(title_obj, str):
            return None
        if not isinstance(permalink, str):
            return None
        if not isinstance(created_utc_obj, (int, float)):
            return None
        title = title_obj
        created_utc = float(created_utc_obj)

        selftext = post.get("selftext")
        if not isinstance(selftext, str):
            selftext = ""

        subreddit = post.get("subreddit")
        if not isinstance(subreddit, str):
            subreddit = ""

        return FeedItem(
            id=None,
            source_kind="reddit",
            source_uid=f"reddit_{name}",
            title=title,
            url=f"https://reddit.com{permalink}",
            published_at=datetime.fromtimestamp(created_utc, tz=timezone.utc),
            raw_payload={
                "score": post.get("score"),
                "num_comments": post.get("num_comments"),
                "subreddit": subreddit,
                "selftext": selftext[:500],
            },
        )
