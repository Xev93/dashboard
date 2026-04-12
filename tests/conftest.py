from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import pytest

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    d = Database(tmp_path / "test.db")
    await d.connect()
    await d.init_schema()
    try:
        yield d
    finally:
        await d.close()


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_feed_items() -> list[FeedItem]:
    ts = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)
    return [
        FeedItem(
            id=None,
            source_kind="arxiv",
            source_uid="2604.12345v1",
            title="A Novel Transformer Architecture",
            url="http://arxiv.org/abs/2604.12345v1",
            published_at=ts,
            raw_payload={"abstract": "test abstract", "authors": ["Jane Researcher"]},
        ),
        FeedItem(
            id=None,
            source_kind="hn",
            source_uid="42000001",
            title="OpenAI releases GPT-5",
            url="https://openai.com/blog/gpt-5",
            published_at=ts,
            raw_payload={
                "points": 342,
                "comment_count": 128,
                "submitted_by": "ai_researcher",
            },
        ),
        FeedItem(
            id=None,
            source_kind="github_trending",
            source_uid="openai/example-llm-agents",
            title="openai/example-llm-agents",
            url="https://github.com/openai/example-llm-agents",
            published_at=ts,
            raw_payload={
                "owner": "openai",
                "name": "example-llm-agents",
                "stars": 42351,
                "language": "Python",
                "description": "LLM agents framework",
            },
        ),
    ]
