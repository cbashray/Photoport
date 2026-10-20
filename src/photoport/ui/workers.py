"""Background worker threads for long-running operations."""

from __future__ import annotations

import logging
import traceback
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

logger = logging.getLogger("photoport.ui.workers")


class WorkerSignals(QObject):
    """Signals for background workers."""

    started = Signal()
    finished = Signal()
    error = Signal(str)
    result = Signal(object)
    progress = Signal(int, int, str)  # completed, total, current_file


class Worker(QRunnable):
    """Generic background worker.

    Runs a callable in a thread pool and emits signals for
    progress, completion, and errors.
    """

    def __init__(self, fn: callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Worker error: %s\n%s", exc, tb)
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class ProgressWorker(QRunnable):
    """Worker that supports progress reporting.

    The callable receives a `progress_callback(completed, total, current_file)`
    function as a keyword argument.
    """

    def __init__(self, fn: callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.kwargs["progress_callback"] = self.signals.progress.emit
            result = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("ProgressWorker error: %s\n%s", exc, tb)
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()
