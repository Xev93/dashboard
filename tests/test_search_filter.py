from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from ai_dashboard.app import AIDashboardApp
from ai_dashboard.config import AppConfig
from ai_dashboard.widgets import FilterBar, SourceTabs


def make_config(tmp_path: Path) -> AppConfig:
    config = AppConfig.defaults()
    config.db_path = tmp_path / "search-filter.db"
    return config


def test_source_tabs_render() -> None:
    tabs = SourceTabs()

    assert "All" in str(tabs.render())


def test_source_tabs_select() -> None:
    tabs = SourceTabs()

    tabs._select(1)

    assert tabs.active_index == 1


@pytest.mark.asyncio
async def test_filter_bar_escape() -> None:
    class FilterBarHarness(App[None]):
        def __init__(self) -> None:
            super().__init__()
            self.closed_count = 0

        def compose(self) -> ComposeResult:
            yield FilterBar(id="filter-bar")

        def on_filter_bar_filter_closed(self, message: FilterBar.FilterClosed) -> None:
            _ = message
            self.closed_count += 1

    app = FilterBarHarness()

    async with app.run_test() as pilot:
        bar = app.query_one("#filter-bar", FilterBar)
        bar.focus()
        bar.value = "claude"

        await pilot.press("escape")

        assert bar.value == ""
        assert app.closed_count == 1


def test_strategy_cycle_toggle(tmp_path: Path) -> None:
    app = AIDashboardApp(make_config(tmp_path))
    workers: list[object] = []

    def capture(worker: object, **_: object) -> None:
        workers.append(worker)
        if inspect.iscoroutine(worker):
            worker.close()

    object.__setattr__(app, "run_worker", capture)

    assert app._ranked_mode is False

    app.action_cycle_strategy()
    assert app._ranked_mode is True

    app.action_cycle_strategy()
    assert app._ranked_mode is False
    assert len(workers) == 2
