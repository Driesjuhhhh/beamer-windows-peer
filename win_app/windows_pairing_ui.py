"""Windows pairing directly in the GUI, with networking off the GUI thread."""
import ipaddress
import threading
import time
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout
import pairing
from sender import is_this_machine


def pair_remote(address, code, discovery_factory=pairing.Discovery, timeout=10):
    address = str(ipaddress.IPv4Address(address.strip()))
    code = code.replace(" ", "")
    if is_this_machine(address):
        raise ValueError("Enter the other PC's IP address, not this PC's address.")
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        raise ValueError("Enter the six-digit code shown on the other PC.")
    discovery = discovery_factory(bind_port=0)
    discovery.start()
    try:
        discovery.find(address)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if discovery.error:
                raise pairing.PairingError(discovery.error)
            pc = next((pc for pc in discovery.pcs() if pc["address"] == address and pc.get("pair_id")), None)
            if pc:
                token, authenticated_name = discovery.pair(pc, code)
                return token, authenticated_name, pc["address"], pc["port"]
            time.sleep(0.05)
        raise pairing.PairingError("No pairing code found. Press Show a code on the other PC and check the firewall.")
    finally:
        discovery.stop()


class WindowsPairDialog(QDialog):
    paired = Signal(str, str, str, int)
    failed = Signal(str)

    def __init__(self, parent, show_code):
        super().__init__(parent)
        self.setWindowTitle("Pair a Windows PC")
        self.setMinimumWidth(420)
        self._busy = False
        layout = QVBoxLayout(self)
        intro = QLabel("On one PC, show a code. On the other, enter that PC's IP address and code.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.host_button = QPushButton("Show a code on this PC")
        self.host_button.clicked.connect(lambda: self._host(show_code))
        layout.addWidget(self.host_button)
        form = QFormLayout()
        self.address = QLineEdit()
        self.address.setPlaceholderText("e.g. 192.168.1.20")
        self.code = QLineEdit()
        self.code.setPlaceholderText("Six-digit code")
        self.code.setMaxLength(7)
        form.addRow("Other PC's IP address", self.address)
        form.addRow("Code shown on that PC", self.code)
        layout.addLayout(form)
        self.join_button = QPushButton("Pair with this Windows PC")
        self.join_button.clicked.connect(self._join)
        layout.addWidget(self.join_button)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button)
        self.failed.connect(self._error)

    def _host(self, show_code):
        if show_code():
            self.accept()

    def _join(self):
        address, code = self.address.text(), self.code.text()
        self._set_busy(True)
        self.status.setText("Pairing…")
        def worker():
            try:
                self.paired.emit(*pair_remote(address, code))
            except Exception as exc:
                self.failed.emit(str(exc))
        threading.Thread(target=worker, daemon=True, name="Beamer-Windows-pair").start()

    def _set_busy(self, busy):
        self._busy = busy
        for widget in (self.host_button, self.join_button, self.address, self.code, self.close_button):
            widget.setEnabled(not busy)

    def _error(self, message):
        self._set_busy(False)
        self.status.setText(message)

    def reject(self):
        if not self._busy:
            super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
