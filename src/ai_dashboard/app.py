from __future__ import annotations

import webbrowser
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message

from ai_dashboard.config import AppConfig
from ai_dashboard.content import ContentFetcher
from ai_dashboard.storage.db import Database
from ai_dashboard.strategies.chronological import ChronologicalAllSourcesStrategy
from ai_dashboard.strategies.base import FeedListStrategy
from ai_dashboard.widgets.feed_list import FeedListWidget
from ai_dashboard.widgets.reading_pane import ReadingPane
from ai_dashboard.workers import PollingOrchestrator


class ItemsArrived(Message):
    def __init__(self, count: int, source_kind: str) -> None:
        super().__init__()
        self.count = count
        self.source_kind = source_kind


class AIDashboardApp(App):
    CSS = """
    #layout { layout: horizontal; height: 100%; }
    #reading-pane { width: 2fr; border: solid $primary; overflow-y: auto; }
    #feed-list { width: 1fr; border: solid $accent; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_all", "Refresh"),
        ("o", "open_url", "Open URL"),
        ("space", "toggle_seen", "Toggle seen"),
        Binding("pageup", "scroll_reading_up", "Page Up", priority=True),
        Binding("pagedown", "scroll_reading_down", "Page Down", priority=True),
        Binding("home", "scroll_reading_home", "Top", priority=True),
        Binding("end", "scroll_reading_end", "Bottom", priority=True),
        ("?", "help", "Help"),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.db = Database(config.db_path)
        self.content_fetcher = ContentFetcher(self.db)
        self.strategy: FeedListStrategy = ChronologicalAllSourcesStrategy(limit=500)
        self.orchestrator: PollingOrchestrator | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="layout"):
            yield ReadingPane(content_fetcher=self.content_fetcher, id="reading-pane")
            yield FeedListWidget(self.strategy, self.db, id="feed-list")

    async def on_load(self) -> None:
        if self.db._conn is None:
            await self.db.connect()
            await self.db.init_schema()

    async def on_mount(self) -> None:
        if self.db._conn is None:
            await self.db.connect()
            await self.db.init_schema()
        await self.content_fetcher.start()
        feed_list = self.query_one(FeedListWidget)
        await feed_list.refresh_items()
        self.orchestrator = PollingOrchestrator(
            self._adapter_specs(),
            self.db,
            self._post_items_arrived,
        )
        await self.orchestrator.start()

    async def on_unmount(self) -> None:
        if self.orchestrator:
            await self.orchestrator.stop(timeout=2.0)
        await self.db.set_user_state(
            "last_check_time", datetime.now(timezone.utc).isoformat()
        )
        await self.content_fetcher.stop()
        await self.db.close()

    async def _post_items_arrived(self, count: int, source_kind: str) -> None:
        self.post_message(ItemsArrived(count=count, source_kind=source_kind))

    async def on_items_arrived(self, message: ItemsArrived) -> None:
        feed_list = self.query_one(FeedListWidget)
        await feed_list.refresh_items()

    async def on_feed_list_widget_item_selected(
        self, message: FeedListWidget.ItemSelected
    ) -> None:
        reading_pane = self.query_one(ReadingPane)
        await reading_pane.show_item(message.item)

    def _adapter_specs(self) -> list[tuple[str, dict]]:
        return [
            (source.kind, source.options)
            for source in self.config.sources
            if source.enabled
        ]

    def action_refresh_all(self) -> None:
        if self.orchestrator:
            self.run_worker(self.orchestrator.refresh_all_now(), exclusive=True)

    def action_open_url(self) -> None:
        try:
            feed_list = self.query_one(FeedListWidget)
            webbrowser.open(feed_list._items[feed_list.cursor_row].url)
        except Exception:
            pass

    def action_toggle_seen(self) -> None:
        try:
            feed_list = self.query_one(FeedListWidget)
            item = feed_list._items[feed_list.cursor_row]
        except Exception:
            return
        if item.id is not None:
            self.run_worker(self._toggle_seen_worker(item.id))

    async def _toggle_seen_worker(self, item_id: int) -> None:
        await self.db.mark_seen(item_id)
        self.post_message(ItemsArrived(count=0, source_kind="local"))

    def action_scroll_reading_up(self) -> None:
        pane = self.query_one("#reading-pane")
        pane.scroll_page_up(animate=False)

    def action_scroll_reading_down(self) -> None:
        pane = self.query_one("#reading-pane")
        pane.scroll_page_down(animate=False)

    def action_scroll_reading_home(self) -> None:
        pane = self.query_one("#reading-pane")
        pane.scroll_home(animate=False)

    def action_scroll_reading_end(self) -> None:
        pane = self.query_one("#reading-pane")
        pane.scroll_end(animate=False)

    def action_help(self) -> None:
        pass


def main() -> int:
    config = AppConfig.load()
    app = AIDashboardApp(config)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
