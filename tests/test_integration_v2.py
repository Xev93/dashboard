from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import httpx
import pytest

from ai_dashboard.config import AppConfig, RankingConfig
from ai_dashboard.sources import build_adapter
from ai_dashboard.sources.base import SourceAdapter
from ai_dashboard.storage.db import Database
from ai_dashboard.strategies.base import FeedListStrategy


def test_v1_config_loads_with_v2_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
db_path = "cache-v1.db"

[[sources]]
kind = "arxiv"

[[sources]]
kind = "hn"

[[sources]]
kind = "github_trending"

[[sources]]
kind = "huggingface"

[[sources]]
kind = "newsletter"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = AppConfig.load(config_path)

    kinds = [source.kind for source in config.sources]
    assert kinds[:5] == ["arxiv", "hn", "github_trending", "huggingface", "newsletter"]
    assert "dblp" in kinds
    assert "hal" in kinds
    assert "lab_blog" in kinds
    assert len(kinds) >= 5
    assert config.ranking == RankingConfig()
    assert config.db_path == Path("cache-v1.db")


def test_v2_config_with_all_sources(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
db_path = "cache-v2.db"

[[sources]]
kind = "arxiv"

[[sources]]
kind = "hn"

[[sources]]
kind = "github_trending"

[[sources]]
kind = "huggingface"

[[sources]]
kind = "newsletter"

[[sources]]
kind = "lab_blog"

[[sources]]
kind = "reddit"

[[sources]]
kind = "papers_with_code"

[ranking]
source_weight_first_party = 0.7
source_weight_community = 0.15
keyword_boost = 0.25
recency_decay_hours = 12.0
skip_penalty = 0.2
skip_window = 30
top_search_terms = 5
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = AppConfig.load(config_path)

    kinds = [source.kind for source in config.sources]
    assert kinds[:8] == [
        "arxiv",
        "hn",
        "github_trending",
        "huggingface",
        "newsletter",
        "lab_blog",
        "reddit",
        "papers_with_code",
    ]
    assert "dblp" in kinds
    assert "hal" in kinds
    assert config.ranking == RankingConfig(
        source_weight_first_party=0.7,
        source_weight_community=0.15,
        keyword_boost=0.25,
        recency_decay_hours=12.0,
        skip_penalty=0.2,
        skip_window=30,
        top_search_terms=5,
    )


@pytest.mark.asyncio
async def test_v2_db_migration_from_v1(tmp_path: Path) -> None:
    db_path = tmp_path / "v1.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE feed_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_kind TEXT NOT NULL,
                source_uid TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                seen INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(source_kind, source_uid)
            );

            CREATE TABLE user_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO feed_items(
                source_kind, source_uid, title, url, published_at, raw_payload, seen, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "arxiv",
                "paper-1",
                "Original title",
                "https://example.com/paper-1",
                "2026-04-12T00:00:00+00:00",
                "{}",
                0,
                "2026-04-12T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO user_state(key, value) VALUES (?, ?)",
            ("last_search", "transformers"),
        )
        conn.commit()
    finally:
        conn.close()

    db = Database(db_path)
    await db.connect()
    try:
        await db.init_schema()

        cursor = await db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("user_search_history",),
        )
        search_history_table = await cursor.fetchone()
        await cursor.close()

        cursor = await db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("item_view_log",),
        )
        item_view_log_table = await cursor.fetchone()
        await cursor.close()

        cursor = await db.connection.execute(
            "SELECT title FROM feed_items WHERE source_kind = ? AND source_uid = ?",
            ("arxiv", "paper-1"),
        )
        feed_item = await cursor.fetchone()
        await cursor.close()

        cursor = await db.connection.execute(
            "SELECT value FROM user_state WHERE key = ?",
            ("last_search",),
        )
        user_state = await cursor.fetchone()
        await cursor.close()

        assert search_history_table is not None
        assert item_view_log_table is not None
        assert feed_item is not None
        assert feed_item[0] == "Original title"
        assert user_state is not None
        assert user_state[0] == "transformers"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_v2_db_migration_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        await db.init_schema()
    finally:
        await db.close()


def test_protocols_unchanged() -> None:
    assert hasattr(FeedListStrategy, "items")
    assert callable(getattr(FeedListStrategy, "items"))
    assert hasattr(SourceAdapter, "fetch")
    assert callable(getattr(SourceAdapter, "fetch"))


def test_no_concrete_strategy_in_feed_list() -> None:
    source = Path("src/ai_dashboard/widgets/feed_list.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    strategy_imports: list[str] = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and "strategies" in node.module
        ):
            strategy_imports.append(node.module)

    assert strategy_imports == ["ai_dashboard.strategies.base"]


def test_no_huggingface_hub() -> None:
    src_root = Path("src")
    matches = [
        path
        for path in src_root.rglob("*")
        if path.is_file()
        and "huggingface_hub" in path.read_text(encoding="utf-8", errors="ignore")
    ]

    assert matches == []


@pytest.mark.asyncio
async def test_all_adapters_registered() -> None:
    async with httpx.AsyncClient() as client:
        for kind in [
            "arxiv",
            "hn",
            "github_trending",
            "huggingface",
            "newsletter",
            "lab_blog",
            "reddit",
            "papers_with_code",
        ]:
            adapter = build_adapter(kind, client, {})
            assert getattr(adapter, "kind") == kind
            assert callable(getattr(adapter, "fetch"))
