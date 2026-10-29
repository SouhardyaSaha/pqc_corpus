"""Cooperative shutdown for long-running workers and their child processes."""

import signal
import subprocess
from types import FrameType


class StopController:
    """Record SIGINT/SIGTERM and forward the signal to the current child process.

    Workers poll `requested` between checkpoints so that they can save progress
    before exiting, instead of being terminated mid-transaction.
    """

    def __init__(self) -> None:
        self.requested = False
        self.child: subprocess.Popen | None = None

    def install(self) -> None:
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, self._handle)

    def _handle(self, signum: int, _frame: FrameType | None) -> None:
        self.requested = True
        if self.child is not None and self.child.poll() is None:
            self.child.send_signal(signum)
