"""The other direction: the PC's keyboard and mouse arriving on this Mac.

A listener on the same port number this Mac reaches Windows on -- different
machines, so one number does for both -- running the same receiver.py the PC
runs, with this Mac's own injector, clipboard and display geometry handed to
it. Nothing about the protocol or the crossing is duplicated here; this module
is only the wiring that says which platform's modules to use and what to do
when input arrives.

The two directions never overlap. Every focus message is passed to the
controller, which stops its own tap from reading a pointer the PC is moving as
a push against this Mac's edge.
"""

import logging
import threading

import clipboard_mac
import desktop_mac
import input_injector_mac
import no_unlock
from receiver import ReceiverServer, ServerState

LOGGER = logging.getLogger("Beamer")


class WindowsInput:
    """Owns the listener and keeps it in step with the settings. `sync` is
    called from the status tick, so a token or port changed in the window
    takes effect without anyone restarting Beamer."""

    def __init__(self, controller, logger=None, arrangement_callback=None):
        self._controller = controller
        self._logger = logger or LOGGER
        # Windows can change the arrangement too, and it reaches this Mac over
        # whichever of the two links is up: this one, or the Mac's own, which
        # bridge.py handles. Both end at the same handler in the app.
        self._arrangement_callback = arrangement_callback
        self._lock = threading.RLock()
        self._running_for = None
        self.state = ServerState.STOPPED
        self.detail = "Not listening"
        self.server = ReceiverServer(
            status_callback=self._on_status,
            clipboard=clipboard_mac,
            unlock=no_unlock,
            desktop=desktop_mac,
            injector=input_injector_mac,
            focus_callback=self._on_focus,
            arrangement_callback=self._on_arrangement,
            self_name="Mac",
            peer_name="PC",
            self_target="mac",
            peer_target="windows",
        )
        controller.send_peer_home = self.server.send_home

    @property
    def receiving(self) -> bool:
        return bool(self._controller.receiving)

    def sync(self, cfg) -> None:
        if not cfg.allow_windows_to_drive:
            # Stopping hands back whatever the PC was driving, the same as a dropped link.
            with self._lock:
                if self._running_for is None:
                    return
                self._running_for = None
            self.server.stop()
            return
        wanted = (cfg.port, cfg.auth_token)
        with self._lock:
            if wanted == self._running_for and self.server.listening:
                return
            if not cfg.auth_token or not cfg.port:
                return
            if self._running_for is not None:
                self.server.stop()
            self._running_for = wanted
        try:
            self.server.start(cfg)
        except Exception:
            self._logger.exception("The listener for the PC's input could not start")

    def stop(self) -> None:
        with self._lock:
            self._running_for = None
        self.server.stop()
        self._controller.set_receiving(False)
        try:
            input_injector_mac.release_all()
        except Exception:
            self._logger.exception("Could not release the keys the PC was holding")

    def send_arrangement(self, mac_edge: str, set_at: int) -> bool:
        """Tell the PC over the link it opened to this Mac. Returns False when
        there is nobody connected, which is not a failure worth reporting --
        the hello carries the arrangement on the next connection anyway."""
        return self.server.send_arrangement(mac_edge, int(set_at))

    def _on_arrangement(self, mac_edge, set_at) -> None:
        if self._arrangement_callback is None:
            return
        self._arrangement_callback(mac_edge, set_at)

    def _on_status(self, state, detail) -> None:
        self.state = state
        self.detail = detail

    def _on_focus(self, target) -> None:
        # The receiver itself releases whatever the PC was holding before
        # this fires, on both machines alike.
        self._controller.set_receiving(target == "mac")
