import datetime as dt
import logging
import os
import tempfile
from unittest import mock

import pytest

import octoprint.plugins.achievements
from octoprint.plugin import PluginSettings

STATS_2025 = {
    "last_version": "1.12.0",
    "seen_versions": 44,
    "server_starts": 1207,
    "prints_started": 92,
    "prints_cancelled": 0,
    "prints_errored": 0,
    "prints_finished": 60,
    "prints_started_per_weekday": {"0": 40, "2": 25, "1": 7, "3": 20},
    "print_duration_total": 13426.333841606101,
    "print_duration_cancelled": 0.0,
    "print_duration_errored": 0.0,
    "print_duration_finished": 1445.5468165731081,
    "longest_print_duration": 841.4034004429996,
    "longest_print_date": 1751532777,
    "files_uploaded": 121,
    "files_deleted": 79,
    "plugins_installed": 7,
    "plugins_uninstalled": 0,
    "most_plugins": 29,
    "achievements": 14,
}


@pytest.fixture()
def initialized_plugin():
    with tempfile.TemporaryDirectory() as basepath:
        plugin = octoprint.plugins.achievements.AchievementsPlugin()
        plugin._data_folder = basepath
        plugin._logger = logging.getLogger(
            "octoprint.plugins.achievements.AchievementsPlugin"
        )

        mocked_settings = mock.MagicMock()
        mocked_settings.get.return_value = None
        plugin._settings = PluginSettings(mocked_settings, plugin_key="achievements")

        yield plugin


def test_load_year(initialized_plugin, time_machine):
    time_machine.move_to(dt.datetime(2025, 12, 25))

    initialized_plugin._load_current_year_file()

    assert initialized_plugin._current_year_stats is not None
    assert initialized_plugin._current_year_stats.year == 2025
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))


def test_year_change(initialized_plugin, time_machine):
    # year change should cause stat reset
    time_machine.move_to(dt.datetime(2025, 12, 31))

    initialized_plugin._load_current_year_file()

    assert initialized_plugin._current_year_stats.year == 2025

    initialized_plugin._current_year_stats.server_starts += 1

    time_machine.move_to(dt.datetime(2026, 1, 1))

    assert initialized_plugin._current_year_stats.server_starts == 0
    assert initialized_plugin._current_year_stats.year == 2026
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))


def test_fix_5223_all_increasing(initialized_plugin, time_machine):
    # all stats increasing -> subtract and reset longest print, achievement, server starts and most plugins
    from octoprint.plugins.achievements.data import YearlyStats

    time_machine.move_to(dt.datetime(2026, 1, 6))

    stats_2025 = YearlyStats(year=2025, **STATS_2025)
    initialized_plugin._write_year_file(stats_2025, year=2025)

    stats_2026 = YearlyStats(year=2026, **STATS_2025)
    stats_2026.server_starts += 1
    initialized_plugin._write_year_file(stats_2026, year=2026)

    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    initialized_plugin._fix_current_year_data()

    assert initialized_plugin._current_year_stats.server_starts == 1
    assert all(
        getattr(initialized_plugin._current_year_stats, key) == 0
        for key in filter(
            lambda x: x != "server_starts",
            octoprint.plugins.achievements.INCREASING_STATS,
        )
    )
    assert all(
        initialized_plugin._current_year_stats.prints_started_per_weekday.get(weekday, 0)
        == 0
        for weekday in range(7)
    )
    assert initialized_plugin._current_year_stats.longest_print_date == 0
    assert initialized_plugin._current_year_stats.longest_print_duration == 0
    assert initialized_plugin._current_year_stats.achievements == 0
    assert initialized_plugin._current_year_stats.most_plugins == 0

    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    assert os.path.exists(
        os.path.join(initialized_plugin._data_folder, ".issue_5223_handled")
    )


def test_fix_5223_all_increasing_but_current_longest_print(
    initialized_plugin, time_machine
):
    # all stats increasing but longest print is from current year -> subtract and reset achievement, server starts and most plugins,
    # longest print should stay
    from octoprint.plugins.achievements.data import YearlyStats

    time_machine.move_to(dt.datetime(2026, 1, 6))

    stats_2025 = YearlyStats(year=2025, **STATS_2025)
    initialized_plugin._write_year_file(stats_2025, year=2025)

    stats_2026 = YearlyStats(year=2026, **STATS_2025)
    stats_2026.server_starts += 1
    stats_2026.longest_print_duration = 200
    stats_2026.longest_print_date = int(dt.datetime(2026, 1, 3, 12, 23, 42).timestamp())
    initialized_plugin._write_year_file(stats_2026, year=2026)

    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    initialized_plugin._fix_current_year_data()

    assert initialized_plugin._current_year_stats.server_starts == 1
    assert all(
        getattr(initialized_plugin._current_year_stats, key) == 0
        for key in filter(
            lambda x: x != "server_starts",
            octoprint.plugins.achievements.INCREASING_STATS,
        )
    )
    assert all(
        initialized_plugin._current_year_stats.prints_started_per_weekday.get(weekday, 0)
        == 0
        for weekday in range(7)
    )
    assert (
        initialized_plugin._current_year_stats.longest_print_date
        == stats_2026.longest_print_date
    )
    assert (
        initialized_plugin._current_year_stats.longest_print_duration
        == stats_2026.longest_print_duration
    )
    assert initialized_plugin._current_year_stats.achievements == 0
    assert initialized_plugin._current_year_stats.most_plugins == 0

    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    assert os.path.exists(
        os.path.join(initialized_plugin._data_folder, ".issue_5223_handled")
    )


def test_fix_5223_longest_print_mismatch(initialized_plugin, time_machine):
    # stats not all increasing, but longest print not in the current year -> full reset
    from octoprint.plugins.achievements.data import YearlyStats

    time_machine.move_to(dt.datetime(2026, 1, 6))

    stats_2025 = YearlyStats(year=2025, **STATS_2025)
    initialized_plugin._write_year_file(stats_2025, year=2025)

    stats_2026 = YearlyStats(year=2026, **STATS_2025)
    stats_2026.server_starts -= 1
    initialized_plugin._write_year_file(stats_2026, year=2026)

    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    initialized_plugin._fix_current_year_data()

    assert all(
        getattr(initialized_plugin._current_year_stats, key) == 0
        for key in octoprint.plugins.achievements.INCREASING_STATS
    )
    assert all(
        initialized_plugin._current_year_stats.prints_started_per_weekday.get(weekday, 0)
        == 0
        for weekday in range(7)
    )
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    assert os.path.exists(
        os.path.join(initialized_plugin._data_folder, ".issue_5223_handled")
    )


def test_fix_5223_noop_1(initialized_plugin, time_machine):
    # stats not all increasing, no longest print -> do nothing
    from octoprint.plugins.achievements.data import YearlyStats

    time_machine.move_to(dt.datetime(2026, 1, 6))

    stats_2025 = YearlyStats(year=2025, **STATS_2025)
    initialized_plugin._write_year_file(stats_2025, year=2025)

    stats_2026 = YearlyStats(year=2026)
    initialized_plugin._write_year_file(stats_2026, year=2026)

    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    initialized_plugin._fix_current_year_data()

    assert all(
        getattr(initialized_plugin._current_year_stats, key) == getattr(stats_2026, key)
        for key in octoprint.plugins.achievements.INCREASING_STATS
    )
    assert all(
        initialized_plugin._current_year_stats.prints_started_per_weekday.get(weekday, 0)
        == stats_2026.prints_started_per_weekday.get(weekday, 0)
        for weekday in range(7)
    )
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    assert os.path.exists(
        os.path.join(initialized_plugin._data_folder, ".issue_5223_handled")
    )


def test_fix_5223_noop_2(initialized_plugin, time_machine):
    # stats not all increasing, no longest print -> do nothing
    from octoprint.plugins.achievements.data import YearlyStats

    time_machine.move_to(dt.datetime(2026, 1, 6))

    stats_2025 = YearlyStats(year=2025, **STATS_2025)
    initialized_plugin._write_year_file(stats_2025, year=2025)

    stats_2026 = YearlyStats(year=2026, **STATS_2025)
    stats_2026.server_starts -= 1
    stats_2026.longest_print_date = 0
    stats_2026.longest_print_duration = 0
    initialized_plugin._write_year_file(stats_2026, year=2026)

    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    initialized_plugin._fix_current_year_data()

    assert all(
        getattr(initialized_plugin._current_year_stats, key) == getattr(stats_2026, key)
        for key in octoprint.plugins.achievements.INCREASING_STATS
    )
    assert all(
        initialized_plugin._current_year_stats.prints_started_per_weekday.get(weekday, 0)
        == stats_2026.prints_started_per_weekday.get(weekday, 0)
        for weekday in range(7)
    )
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    assert os.path.exists(
        os.path.join(initialized_plugin._data_folder, ".issue_5223_handled")
    )


def test_fix_5223_sentinel_set(initialized_plugin, time_machine):
    # sentinel -> do nothing
    from octoprint.plugins.achievements.data import YearlyStats

    time_machine.move_to(dt.datetime(2026, 1, 6))

    stats_2025 = YearlyStats(year=2025, **STATS_2025)
    initialized_plugin._write_year_file(stats_2025, year=2025)

    stats_2026 = YearlyStats(year=2026, **STATS_2025)
    stats_2026.server_starts += 1
    initialized_plugin._write_year_file(stats_2026, year=2026)

    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))

    open(
        os.path.join(initialized_plugin._data_folder, ".issue_5223_handled"), "a"
    ).close()

    initialized_plugin._fix_current_year_data()

    assert (
        initialized_plugin._current_year_stats.server_starts == stats_2026.server_starts
    )
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2025.json"))
    assert os.path.exists(os.path.join(initialized_plugin._data_folder, "2026.json"))
