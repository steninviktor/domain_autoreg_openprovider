from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RunnerSnapshot:
    mode: str
    interval_seconds: float | None
    last_error: str | None
    last_run_at: float | None
    next_run_at: float | None = None


class GuiRunner:
    def __init__(self, run_once_callback: Callable[[], None]):
        self._run_once_callback = run_once_callback
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._mode = "stopped"
        self._interval_seconds: float | None = None
        self._last_error: str | None = None
        self._last_run_at: float | None = None
        self._next_run_at: float | None = None

    def snapshot(self) -> RunnerSnapshot:
        with self._lock:
            return RunnerSnapshot(
                mode=self._mode,
                interval_seconds=self._interval_seconds,
                last_error=self._last_error,
                last_run_at=self._last_run_at,
                next_run_at=self._next_run_at,
            )

    def run_once(self) -> bool:
        with self._lock:
            if self._mode in {"running_once", "running_periodic", "stopping"}:
                return False
            self._mode = "running_once"
            self._last_error = None
            self._next_run_at = None
        try:
            self._run_once_callback()
        except Exception as exc:
            with self._lock:
                self._mode = "error"
                self._last_error = str(exc)
                self._last_run_at = time.time()
            return False
        with self._lock:
            self._mode = "stopped"
            self._last_run_at = time.time()
            self._next_run_at = None
        return True

    def start_periodic(self, interval_seconds: float) -> bool:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        with self._lock:
            if self._mode in {"running_once", "running_periodic", "stopping"}:
                return False
            self._mode = "running_periodic"
            self._interval_seconds = interval_seconds
            self._last_error = None
            self._next_run_at = None
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._periodic_loop, daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            if self._mode != "running_periodic" or thread is None:
                if self._mode == "error":
                    self._mode = "stopped"
                return
            self._mode = "stopping"
            self._stop_event.set()
        thread.join(timeout=5)
        with self._lock:
            if self._mode != "error":
                self._mode = "stopped"
            self._thread = None
            self._interval_seconds = None
            self._next_run_at = None

    def _periodic_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                self._next_run_at = None
            try:
                self._run_once_callback()
            except Exception as exc:
                with self._lock:
                    self._mode = "error"
                    self._last_error = str(exc)
                    self._last_run_at = time.time()
                    self._next_run_at = None
                return
            with self._lock:
                now = time.time()
                self._last_run_at = now
                interval = self._interval_seconds or 1
                self._next_run_at = now + interval
            if self._stop_event.wait(interval):
                break
        with self._lock:
            if self._mode != "error":
                self._mode = "stopped"
                self._thread = None
                self._interval_seconds = None
                self._next_run_at = None
