"""Generic long-running subprocess manager.

Replaces the six near-identical (process, log_fh, lock) triplets that used to
live in ``state.py`` and the matching ``_is_X_running`` / ``X_start`` /
``X_status`` / ``X_stop`` blocks in ``routers/ml_ops.py``.

Each subprocess kind (prefetch, rescore, retrain, pack, vscore, tag_train) gets
one ``ManagedSubprocess`` instance, registered in ``state._subprocesses``.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import IO, Any, Optional

from fastapi import HTTPException


class ManagedSubprocess:
    """Tracks a single long-running subprocess + its log file + a serialising lock.

    The class owns the ``(process, log_fh, lock)`` triplet and provides
    ``is_running`` / ``start`` / ``stop`` / ``status`` / ``cleanup`` as the only
    public surface. Endpoint handlers continue to build the actual command,
    environment, and any header lines themselves.
    """

    def __init__(
        self,
        name: str,
        log_path: Path,
        pgrep_pattern: Optional[str] = None,
    ) -> None:
        self.name = name
        self.log_path = log_path
        self.pgrep_pattern = pgrep_pattern
        self.lock: asyncio.Lock = asyncio.Lock()
        # Guards cross-thread reads/writes of process + log_fh: sync helpers
        # (is_running, status snapshot) run via asyncio.to_thread on a worker
        # thread while async start/stop mutate these fields on the loop thread.
        self._sync_lock: threading.Lock = threading.Lock()
        self.process: Optional[subprocess.Popen] = None
        self.log_fh: Optional[IO[Any]] = None

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """Return True if our tracked process or any pgrep-matching process is alive."""
        with self._sync_lock:
            proc = self.process
            if proc is not None:
                ret = proc.poll()
                if ret is None:
                    return True
                # Tracked process has exited; clear handle + log fh
                self.process = None
                self._close_log_fh()
        if self.pgrep_pattern:
            try:
                result = subprocess.run(
                    ["pgrep", "-f", self.pgrep_pattern],
                    capture_output=True,
                    timeout=5,
                )
                return result.returncode == 0
            except Exception:
                return False
        return False

    def _close_log_fh(self) -> None:
        fh = self.log_fh
        if fh is not None and not fh.closed:
            try:
                fh.close()
            except Exception:
                pass
        self.log_fh = None

    async def read_log_tail(self, max_bytes: int = 5000) -> str:
        """Return up to ``max_bytes`` of the log tail, off the event loop."""

        def _read() -> str:
            if not self.log_path.exists():
                return ""
            try:
                with open(self.log_path, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - max_bytes))
                    return f.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        return await asyncio.to_thread(_read)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(
        self,
        cmd: list[str],
        env: Optional[dict] = None,
        cwd: Optional[Path | str] = None,
        append_log: bool = False,
        header: Optional[str] = None,
        wait_after: float = 0.0,
    ) -> dict:
        """Spawn the subprocess. Returns ``{"started": True, "pid": int}``.

        Raises ``HTTPException(409)`` if already running, or
        ``HTTPException(500)`` if the process exits during the optional
        ``wait_after`` smoke-test window.
        """
        async with self.lock:
            if await asyncio.to_thread(self.is_running):
                raise HTTPException(status_code=409, detail="already_running")

            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append_log else "w"
            try:
                log_fh = open(self.log_path, mode)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"failed_to_open_log:{e}")

            if header:
                try:
                    log_fh.write(header)
                    log_fh.flush()
                except Exception:
                    pass

            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(cwd) if cwd is not None else None,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=env,
                )
            except Exception as e:
                if not log_fh.closed:
                    log_fh.close()
                raise HTTPException(status_code=500, detail=f"spawn_failed:{e}")

            with self._sync_lock:
                self.process = proc
                self.log_fh = log_fh

            if wait_after > 0:
                await asyncio.sleep(wait_after)
                if proc.poll() is not None:
                    code = proc.returncode
                    with self._sync_lock:
                        self.process = None
                        self._close_log_fh()
                    raise HTTPException(status_code=500, detail=f"exited:{code}")

            return {"started": True, "pid": proc.pid}

    async def stop(self, kill_external: bool = False) -> dict:
        """Stop the tracked subprocess (and optionally pgrep-matching strays).

        Returns ``{"stopped": bool}`` where the bool reflects whether anything
        was actually killed. Holds ``self.lock`` for the duration.
        """
        async with self.lock:
            killed = await self._terminate_tracked()
            if kill_external and self.pgrep_pattern:
                killed = await asyncio.to_thread(self._pgrep_kill) or killed
            return {"stopped": killed}

    async def _terminate_tracked(self) -> bool:
        with self._sync_lock:
            proc = self.process
        if proc is None or proc.poll() is not None:
            # Already exited but maybe log handle still open
            if proc is not None:
                with self._sync_lock:
                    self.process = None
                    self._close_log_fh()
            return False
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                await asyncio.to_thread(proc.wait, 5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        except Exception:
            try:
                proc.terminate()
                try:
                    await asyncio.to_thread(proc.wait, 5)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            except Exception:
                pass
        with self._sync_lock:
            self.process = None
            self._close_log_fh()
        return True

    def _pgrep_kill(self) -> bool:
        """Best-effort SIGTERM to any process matching ``pgrep_pattern``."""
        if not self.pgrep_pattern:
            return False
        killed = False
        try:
            result = subprocess.run(
                ["pgrep", "-f", self.pgrep_pattern],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for pid_str in result.stdout.strip().split("\n"):
                pid_str = pid_str.strip()
                if not pid_str:
                    continue
                try:
                    os.kill(int(pid_str), signal.SIGTERM)
                    killed = True
                except (ProcessLookupError, ValueError):
                    pass
        except Exception:
            pass
        return killed

    async def status(self, include_log: bool = True) -> dict:
        """Return ``{running, last_exit_code, log_tail}``.

        ``last_exit_code`` is the exit code of the most recently tracked
        subprocess if it has finished and not yet been overwritten; ``None``
        otherwise.
        """
        running = await asyncio.to_thread(self.is_running)
        last_exit_code: Optional[int] = None
        with self._sync_lock:
            proc = self.process
        if not running and proc is not None:
            last_exit_code = proc.poll()
        log_tail = await self.read_log_tail() if include_log else ""
        return {
            "running": running,
            "last_exit_code": last_exit_code,
            "log_tail": log_tail,
        }

    async def cleanup(self) -> None:
        """Lifespan-shutdown hook: terminate the process and close the log fh."""
        with self._sync_lock:
            proc = self.process
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    await asyncio.to_thread(proc.wait, 5)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        with self._sync_lock:
            self.process = None
            self._close_log_fh()


def make_header(label: str, *, extra: str | None = None) -> str:
    """Build the ``=== <label> started at <ts> [extra] ===`` log header."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if extra:
        return f"=== {label} started at {ts} ({extra}) ===\n"
    return f"=== {label} started at {ts} ===\n"
