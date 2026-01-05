import logging
import signal

from resilientdns.main import _register_signal_handlers


class DummyLoop:
    def __init__(self) -> None:
        self.calls = []

    def add_signal_handler(self, sig, callback) -> None:
        self.calls.append(sig)


def test_registers_sighup_when_available():
    loop = DummyLoop()
    logger = logging.getLogger("resilientdns.test")

    _register_signal_handlers(loop, [lambda: None], lambda: None, logger)

    assert signal.SIGINT in loop.calls
    assert signal.SIGTERM in loop.calls
    if hasattr(signal, "SIGHUP"):
        assert signal.SIGHUP in loop.calls
