"""Unit tests for host memory and legacy-daemon helpers."""

from __future__ import annotations

from pathlib import Path

from tb.lib.host_health import (
    LegacyDaemonStatus,
    MemoryStats,
    legacy_daemon_check_status,
    memory_check_status,
    read_memory_stats,
)


def test_read_memory_stats(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       16278920 kB\n"
        "MemAvailable:    5138088 kB\n"
        "SwapTotal:       4194300 kB\n"
        "SwapFree:         972484 kB\n",
        encoding="utf-8",
    )
    stats = read_memory_stats(meminfo)
    assert stats.mem_total_kb == 16278920
    assert stats.mem_available_kb == 5138088
    assert round(stats.swap_used_pct, 1) == 76.8


def test_memory_check_pass() -> None:
    stats = MemoryStats(
        mem_total_kb=16 * 1024 * 1024,
        mem_available_kb=8 * 1024 * 1024,
        swap_total_kb=4 * 1024 * 1024,
        swap_free_kb=3 * 1024 * 1024,
    )
    status, _ = memory_check_status(stats)
    assert status == "PASS"


def test_memory_check_warn_on_swap() -> None:
    stats = MemoryStats(
        mem_total_kb=16 * 1024 * 1024,
        mem_available_kb=6 * 1024 * 1024,
        swap_total_kb=4 * 1024 * 1024,
        swap_free_kb=1 * 1024 * 1024,
    )
    status, detail = memory_check_status(stats)
    assert status == "WARN"
    assert "75%" in detail or "swap" in detail


def test_memory_check_fail_on_extreme_swap() -> None:
    stats = MemoryStats(
        mem_total_kb=16 * 1024 * 1024,
        mem_available_kb=1 * 1024 * 1024,
        swap_total_kb=4 * 1024 * 1024,
        swap_free_kb=100 * 1024,
    )
    status, detail = memory_check_status(stats)
    assert status == "FAIL"
    assert "launch blocker" in detail


def test_legacy_daemon_pass() -> None:
    rows = [
        LegacyDaemonStatus("theeyebeta-engine.service", "inactive"),
        LegacyDaemonStatus("theeyebeta-trask.service", "inactive"),
    ]
    status, detail = legacy_daemon_check_status(rows)
    assert status == "PASS"
    assert "no legacy" in detail


def test_legacy_engine_fail() -> None:
    rows = [LegacyDaemonStatus("theeyebeta-engine.service", "active")]
    status, detail = legacy_daemon_check_status(rows)
    assert status == "FAIL"
    assert "theeyebeta-engine.service" in detail


def test_legacy_trask_warn() -> None:
    rows = [LegacyDaemonStatus("theeyebeta-trask.service", "active")]
    status, _ = legacy_daemon_check_status(rows)
    assert status == "WARN"
