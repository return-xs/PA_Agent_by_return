"""1 Hz data refresh loop running on a dedicated QThread."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from pa_agent.data.base import DataSource, DataSourceTransientError, KlineBar

if TYPE_CHECKING:
    from pa_agent.util.threading import CancelToken

logger = logging.getLogger(__name__)

from PyQt6.QtCore import QThread, pyqtSignal, QObject


class RefreshLoop(QThread):
    """Fetches the latest K-line snapshot every *interval_ms* milliseconds.

    Signals
    -------
    frame_ready(list[KlineBar])
        Emitted after each successful fetch with the raw bar list (newest-first).
    status_changed(str)
        Emitted with a human-readable status string (e.g. "数据延迟").
    """

    frame_ready = pyqtSignal(list)
    status_changed = pyqtSignal(str)

    def __init__(
        self,
        data_source: DataSource,
        n_bars: int,
        interval_ms: int = 1000,
        cancel_token: "CancelToken | None" = None,
        parent: "QObject | None" = None,
    ) -> None:
        super().__init__(parent)
        self._source = data_source
        self._n_bars = n_bars
        self._interval_ms = interval_ms
        self._cancel_token = cancel_token
        self._consecutive_failures = 0
        self._failure_threshold_s = 5.0

    def run(self) -> None:  # noqa: C901
        """Main loop — runs on the worker thread."""
        failure_start: float | None = None

        while True:
            if self._cancel_token is not None and self._cancel_token.is_set():
                logger.debug("RefreshLoop cancelled")
                break

            t0 = time.monotonic()
            try:
                bars = self._source.latest_snapshot(self._n_bars + 5)
                self._consecutive_failures = 0
                failure_start = None
                if bars:
                    self.frame_ready.emit(bars)

            except DataSourceTransientError as exc:
                logger.debug("RefreshLoop transient error: %s", exc)
                self._consecutive_failures += 1
                if failure_start is None:
                    failure_start = time.monotonic()
                user_msg = str(exc).strip()
                if user_msg:
                    self.status_changed.emit(user_msg)
                elapsed = time.monotonic() - failure_start
                if elapsed >= self._failure_threshold_s and not user_msg:
                    self.status_changed.emit("数据延迟")
            except Exception as exc:  # noqa: BLE001
                logger.error("RefreshLoop unexpected error: %s", exc, exc_info=True)

            elapsed_ms = (time.monotonic() - t0) * 1000
            sleep_ms = max(0.0, self._interval_ms - elapsed_ms)
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
