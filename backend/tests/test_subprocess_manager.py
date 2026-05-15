"""Tests for subprocess_manager.ManagedSubprocess.

Uses real (very short) python subprocesses rather than Popen mocks, so we
exercise the actual signal/wait paths. Each test cleans up via the
``managed`` fixture so a leaking process can't poison later tests.
"""

import asyncio
import sys

import pytest
import pytest_asyncio
from fastapi import HTTPException

from subprocess_manager import ManagedSubprocess, make_header


@pytest_asyncio.fixture()
async def managed(tmp_path):
    """Yield a fresh ManagedSubprocess and force-cleanup at teardown."""
    log_path = tmp_path / "managed.log"
    m = ManagedSubprocess(name="test", log_path=log_path, pgrep_pattern=None)
    try:
        yield m
    finally:
        # Best-effort cleanup: terminate any process we may have left running.
        await m.cleanup()


# ---------------------------------------------------------------------------
# is_running
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_running_initially_false(managed):
    assert managed.is_running() is False


@pytest.mark.asyncio
async def test_start_sets_is_running_true(managed):
    # A 2-second sleep is long enough to observe is_running() as True.
    cmd = [sys.executable, "-c", "import time; time.sleep(2)"]
    result = await managed.start(cmd)
    assert result["started"] is True
    assert isinstance(result["pid"], int)
    assert managed.is_running() is True


@pytest.mark.asyncio
async def test_is_running_false_after_natural_exit(managed):
    # Process exits almost immediately.
    cmd = [sys.executable, "-c", "pass"]
    await managed.start(cmd)
    # Give it time to exit.
    for _ in range(50):
        if not managed.is_running():
            break
        await asyncio.sleep(0.05)
    assert managed.is_running() is False
    # is_running() side-effect: process handle is cleared when exited.
    assert managed.process is None
    # log_fh must be closed on exit detection.
    assert managed.log_fh is None


# ---------------------------------------------------------------------------
# start: 409 when already running
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_when_running_raises_409(managed):
    cmd = [sys.executable, "-c", "import time; time.sleep(2)"]
    await managed.start(cmd)
    with pytest.raises(HTTPException) as excinfo:
        await managed.start(cmd)
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "already_running"


# ---------------------------------------------------------------------------
# start: header writing & log truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_writes_header(managed):
    cmd = [sys.executable, "-c", "print('hello-from-subprocess')"]
    header = "=== HEADER LINE ===\n"
    await managed.start(cmd, header=header)
    # Wait for it to flush + exit
    for _ in range(50):
        if managed.process is None or managed.process.poll() is not None:
            break
        await asyncio.sleep(0.05)
    # is_running clears log_fh on exit, and read_log_tail is async-safe.
    tail = await managed.read_log_tail()
    assert "HEADER LINE" in tail
    assert "hello-from-subprocess" in tail


# ---------------------------------------------------------------------------
# start: wait_after smoke window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_with_wait_after_detects_immediate_exit(managed):
    """If the process dies inside the wait_after window, start raises 500."""
    # Exit code 7, instantaneous.
    cmd = [sys.executable, "-c", "import sys; sys.exit(7)"]
    with pytest.raises(HTTPException) as excinfo:
        await managed.start(cmd, wait_after=0.5)
    assert excinfo.value.status_code == 500
    # detail format: "exited:7"
    assert "exited" in excinfo.value.detail
    # State must be cleaned up after the failure.
    assert managed.process is None
    assert managed.log_fh is None


# ---------------------------------------------------------------------------
# stop / cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_terminates_running_process(managed):
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    await managed.start(cmd)
    assert managed.is_running() is True
    result = await managed.stop()
    assert result["stopped"] is True
    # After stop, is_running should be False and state cleared.
    assert managed.is_running() is False
    assert managed.process is None


@pytest.mark.asyncio
async def test_stop_when_not_running_returns_false(managed):
    result = await managed.stop()
    assert result["stopped"] is False


@pytest.mark.asyncio
async def test_cleanup_kills_process_and_closes_log(managed):
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    await managed.start(cmd)
    log_fh = managed.log_fh
    assert log_fh is not None and not log_fh.closed
    await managed.cleanup()
    # Process gone.
    assert managed.process is None
    # Log fh closed.
    assert managed.log_fh is None


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_running_shape(managed):
    cmd = [sys.executable, "-c", "import time; time.sleep(2)"]
    await managed.start(cmd)
    st = await managed.status(include_log=True)
    assert set(st.keys()) == {"running", "last_exit_code", "log_tail"}
    assert st["running"] is True
    assert st["last_exit_code"] is None
    assert isinstance(st["log_tail"], str)


@pytest.mark.asyncio
async def test_status_after_completion(managed):
    cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
    await managed.start(cmd)
    # Wait for exit.
    for _ in range(50):
        if not managed.is_running():
            break
        await asyncio.sleep(0.05)
    st = await managed.status(include_log=True)
    assert st["running"] is False


# ---------------------------------------------------------------------------
# read_log_tail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_log_tail_missing_file_returns_empty(managed):
    # log_path does not exist yet (no start has happened).
    assert managed.log_path.exists() is False
    tail = await managed.read_log_tail()
    assert tail == ""


@pytest.mark.asyncio
async def test_read_log_tail_returns_recent_bytes(managed, tmp_path):
    # Write a known string to the log file.
    managed.log_path.write_bytes(b"x" * 100 + b"END")
    tail = await managed.read_log_tail(max_bytes=10)
    # Last 10 bytes should include "END".
    assert "END" in tail
    assert len(tail) <= 10


# ---------------------------------------------------------------------------
# make_header
# ---------------------------------------------------------------------------


def test_make_header_basic_format():
    h = make_header("retrain")
    assert h.startswith("=== retrain started at ")
    assert h.endswith("===\n")


def test_make_header_with_extra():
    h = make_header("vscore", extra="model=v3")
    assert "vscore" in h
    assert "(model=v3)" in h
