from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class SourceKind(StrEnum):
    ARXIV = "arxiv"
    HN = "hn"
    GITHUB_TRENDING = "github_trending"
    HUGGINGFACE = "huggingface"
    NEWSLETTER = "newsletter"


@dataclass(frozen=True, slots=True)
class FeedItem:
    id: int | None
    source_kind: str
    source_uid: str
    title: str
    url: str
    published_at: datetime
    raw_payload: dict[str, Any] = field(default_factory=dict)
    seen: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_row(self) -> tuple[str, str, str, str, str, str, int, str]:
        return (
            self.source_kind,
            self.source_uid,
            self.title,
            self.url,
            self.published_at.isoformat(),
            json.dumps(self.raw_payload, separators=(",", ":"), ensure_ascii=False),
            1 if self.seen else 0,
            self.created_at.isoformat(),
        )

    @classmethod
    def from_row(cls, row: Any) -> "FeedItem":
        return cls(
            id=row["id"],
            source_kind=row["source_kind"],
            source_uid=row["source_uid"],
            title=row["title"],
            url=row["url"],
            published_at=_parse_iso(row["published_at"]),
            raw_payload=json.loads(row["raw_payload"]) if row["raw_payload"] else {},
            seen=bool(row["seen"]),
            created_at=_parse_iso(row["created_at"]),
        )

    def with_id(self, new_id: int) -> "FeedItem":
        return replace(self, id=new_id)


def _parse_iso(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
