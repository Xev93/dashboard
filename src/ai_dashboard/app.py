from __future__ import annotations

import logging
import os
import webbrowser
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message

from .config import AppConfig
from .content import ContentFetcher
from .daemon import PID_PATH
from .storage.db import Database
from .strategies.base import FeedListStrategy
from .strategies.by_source import BySourceStrategy
from .strategies.chronological import ChronologicalAllSourcesStrategy
from .strategies.filtered import FilteredStrategy
from .strategies.heuristic import HeuristicRankingStrategy
from .widgets.feed_list import FeedListWidget
from .widgets.filter_bar import FilterBar
from .widgets.reading_pane import ReadingPane
from .widgets.source_tabs import SourceTabs
from .workers import PollingOrchestrator

logger = logging.getLogger(__name__)


class ItemsArrived(Message):
    def __init__(self, count: int, source_kind: str) -> None:
        super().__init__()
        self.count = count
        self.source_kind = source_kind


class AIDashboardApp(App[None]):
    CSS = """
    #source-tabs { dock: top; height: 1; }
    #layout { layout: horizontal; height: 1fr; }
    #reading-pane { width: 2fr; height: 100%; border: solid $primary; overflow-y: scroll; }
    #feed-list { width: 1fr; height: 100%; border: solid $accent; }
    #filter-bar { dock: bottom; display: none; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_all", "Refresh"),
        ("o", "open_url", "Open URL"),
        ("space", "toggle_seen", "Toggle seen"),
        *[Binding(str(i), f"select_tab({i})", show=False) for i in range(1, 14)],
        Binding("tab", "next_tab", "Next tab", priority=True),
        Binding("shift+tab", "prev_tab", "Prev tab", priority=True, show=False),
        Binding("pageup", "scroll_reading_up", "Page Up", priority=True),
        Binding("pagedown", "scroll_reading_down", "Page Down", priority=True),
        Binding("home", "scroll_reading_home", "Top", priority=True),
        Binding("end", "scroll_reading_end", "Bottom", priority=True),
        ("/", "open_filter", "Filter"),
        ("s", "cycle_strategy", "Ranked/Chrono"),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.db = Database(config.db_path)
        self.content_fetcher = ContentFetcher(self.db)
        self._ranked_mode: bool = False
        self._base_strategy: FeedListStrategy = self._default_strategy()
        self._active_strategy: FeedListStrategy = self._base_strategy
        self.strategy: FeedListStrategy = self._active_strategy
        self.orchestrator: PollingOrchestrator | None = None

    def compose(self) -> ComposeResult:
        yield SourceTabs(id="source-tabs")
        with Horizontal(id="layout"):
            yield ReadingPane(content_fetcher=self.content_fetcher, id="reading-pane")
            yield FeedListWidget(self.strategy, self.db, id="feed-list")
        yield FilterBar(id="filter-bar")

    async def on_load(self) -> None:
        if not self.db.is_connected:
            await self.db.connect()
            await self.db.init_schema()

    async def on_mount(self) -> None:
        await self.content_fetcher.start()
        feed_list = self.query_one(FeedListWidget)
        await feed_list.refresh_items()

        if self._is_daemon_running():
            self.orchestrator = None
            self.set_interval(30, self._periodic_refresh)
            self.log("Daemon detected, TUI in client mode")
        else:
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

    def _is_daemon_running(self) -> bool:
        """Check if daemon is running via PID file + identity validation."""
        if not PID_PATH.exists():
            return False
        try:
            lines = PID_PATH.read_text().strip().splitlines()
            if len(lines) < 2:
                PID_PATH.unlink(missing_ok=True)
                return False
            pid = int(lines[0])
            identity = lines[1]
            if identity != "ai-dashboard-daemon":
                PID_PATH.unlink(missing_ok=True)
                return False
            os.kill(pid, 0)
            return True
        except (ValueError, OSError, ProcessLookupError):
            PID_PATH.unlink(missing_ok=True)
            return False

    async def on_items_arrived(self, message: ItemsArrived) -> None:
        feed_list = self.query_one(FeedListWidget)
        await feed_list.refresh_items()

    async def _periodic_refresh(self) -> None:
        """When daemon is polling, periodically refresh feed from DB."""
        feed_list = self.query_one(FeedListWidget)
        await feed_list.refresh_items()

    async def on_feed_list_widget_item_selected(
        self, message: FeedListWidget.ItemSelected
    ) -> None:
        reading_pane = self.query_one(ReadingPane)
        await reading_pane.show_item(message.item)

    async def on_feed_list_widget_item_viewed(
        self, message: FeedListWidget.ItemViewed
    ) -> None:
        await self.db.record_item_view(
            message.item.source_kind, message.item.source_uid, "viewed"
        )

    async def on_feed_list_widget_item_skipped(
        self, message: FeedListWidget.ItemSkipped
    ) -> None:
        await self.db.record_item_view(
            message.item.source_kind, message.item.source_uid, "skipped"
        )

    async def on_source_tabs_tab_changed(self, message: SourceTabs.TabChanged) -> None:
        if message.source_kind is None:
            self._base_strategy = self._default_strategy()
        else:
            self._base_strategy = BySourceStrategy(message.source_kind)
        self._active_strategy = self._base_strategy
        await self._apply_strategy()

    async def on_filter_bar_filter_changed(
        self, message: FilterBar.FilterChanged
    ) -> None:
        if message.text:
            self._active_strategy = FilteredStrategy(self._base_strategy, message.text)
        else:
            self._active_strategy = self._base_strategy
        await self._apply_strategy()

    async def on_filter_bar_filter_closed(
        self, message: FilterBar.FilterClosed
    ) -> None:
        _ = message
        final_text = self.query_one("#filter-bar", FilterBar).value.strip()
        if final_text and len(final_text) >= 3:
            await self.db.record_search_term(final_text)
        self._active_strategy = self._base_strategy
        self.query_one("#filter-bar", FilterBar).display = False
        await self._apply_strategy()

    def _adapter_specs(self) -> list[tuple[str, dict[str, object]]]:
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
            url = feed_list._items[feed_list.cursor_row].url
            if not url or not url.startswith(("http://", "https://")):
                return
            webbrowser.open(url)
        except Exception:
            logger.warning("Failed to open URL", exc_info=True)

    def action_toggle_seen(self) -> None:
        try:
            feed_list = self.query_one(FeedListWidget)
            item = feed_list._items[feed_list.cursor_row]
        except Exception:
            logger.warning("Failed to toggle seen", exc_info=True)
            return
        if item.id is not None:
            self.run_worker(self._toggle_seen_worker(item.id))

    def action_open_filter(self) -> None:
        bar = self.query_one("#filter-bar", FilterBar)
        bar.display = True
        bar.focus()

    def action_cycle_strategy(self) -> None:
        self._ranked_mode = not self._ranked_mode
        self._base_strategy = self._default_strategy()
        self._active_strategy = self._base_strategy
        self.run_worker(self._apply_strategy())

    async def _toggle_seen_worker(self, item_id: int) -> None:
        await self.db.mark_seen(item_id)
        self.post_message(ItemsArrived(count=0, source_kind="local"))

    def _default_strategy(self) -> FeedListStrategy:
        if self._ranked_mode:
            return HeuristicRankingStrategy(self.config.ranking)
        return ChronologicalAllSourcesStrategy(limit=500)

    async def _apply_strategy(self) -> None:
        feed_list = self.query_one(FeedListWidget)
        self.strategy = self._active_strategy
        feed_list.strategy = self._active_strategy
        await feed_list.refresh_items()

    def action_scroll_reading_up(self) -> None:
        pane = self.query_one("#reading-pane")
        pane.scroll_relative(y=-pane.container_size.height, animate=False)

    def action_scroll_reading_down(self) -> None:
        pane = self.query_one("#reading-pane")
        pane.scroll_relative(y=pane.container_size.height, animate=False)

    def action_scroll_reading_home(self) -> None:
        pane = self.query_one("#reading-pane")
        pane.scroll_home(animate=False)

    def action_scroll_reading_end(self) -> None:
        pane = self.query_one("#reading-pane")
        pane.scroll_end(animate=False)

    def action_select_tab(self, index: int) -> None:
        self.query_one(SourceTabs).select_tab(index - 1)

    def action_next_tab(self) -> None:
        tabs = self.query_one(SourceTabs)
        tabs.select_tab((tabs.active_index + 1) % len(tabs.TABS))

    def action_prev_tab(self) -> None:
        tabs = self.query_one(SourceTabs)
        tabs.select_tab((tabs.active_index - 1) % len(tabs.TABS))


def main() -> int:
    config = AppConfig.load()
    app = AIDashboardApp(config)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
