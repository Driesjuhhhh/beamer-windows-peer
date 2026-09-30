"""Advanced Crossing editor and authenticated Windows display controls."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QBrush, QPen
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QGraphicsView, QGraphicsScene, QGraphicsRectItem, QApplication)
import desktop_win
import display_layout as layout_model


class ScreenTile(QGraphicsRectItem):
    def __init__(self, screen, number):
        super().__init__(0, 0, screen["width"], screen["height"])
        self.screen = screen
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable | self.GraphicsItemFlag.ItemIsSelectable)
        self.setBrush(QBrush(QColor("#315c9c" if screen["owner"] == "local" else "#397856")))
        self.setPen(QPen(QColor("white"), 8))

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # Snap to another display's edge while retaining the chosen height/width alignment.
        candidates = []
        for other in self.scene().items():
            if not isinstance(other, ScreenTile) or other is self:
                continue
            a, b = self.rect().translated(self.scenePos()), other.rect().translated(other.scenePos())
            for delta, axis in ((b.right()-a.left(), "x"), (b.left()-a.right(), "x"),
                                (b.bottom()-a.top(), "y"), (b.top()-a.bottom(), "y")):
                overlaps = (a.top() < b.bottom() and a.bottom() > b.top()) if axis == "x" else (a.left() < b.right() and a.right() > b.left())
                if overlaps and abs(delta) < 180:
                    candidates.append((abs(delta), delta, axis))
        if candidates:
            _, delta, axis = min(candidates)
            self.setPos(self.x()+delta if axis == "x" else self.x(), self.y()+delta if axis == "y" else self.y())


class AdvancedDisplays(QWidget):
    incoming = Signal(object)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.peer = []
        self.local = []
        self.labels = []
        self.incoming.connect(self.receive)
        self.app.sender.display_control = self.incoming.emit
        self.app.server.display_control = self.incoming.emit
        body = QVBoxLayout(self)
        self.note = QLabel("Drag screens until their edges touch. Blue: this PC; green: other PC. Select a screen to identify it. This changes Beamer crossing, not Windows display settings.")
        self.note.setWordWrap(True)
        body.addWidget(self.note)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setMinimumHeight(230)
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        body.addWidget(self.view)
        actions = QHBoxLayout()
        for text, callback in (("Identify", self.identify), ("Refresh screens", self.refresh),
                               ("Reset layout", self.reset_layout), ("Apply layout", self.apply)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        body.addLayout(actions)
        self.status = QLabel("Waiting for the other PC's screens…")
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.announce)
        self.timer.start()
        self.refresh()

    def supported(self):
        return self.app._config is not None and self.app._config.peer_platform == "windows"

    def send(self, data):
        if not self.supported():
            return False
        return self.app.sender.send_display_control(data)

    def announce(self):
        if not self.supported():
            self.status.setText("Advanced screen layout requires Windows Peer Beamer on both PCs.")
            return
        try:
            current = desktop_win.displays()
        except (OSError, RuntimeError):
            self.status.setText("Windows could not read the screens. Try Refresh screens.")
            return
        if current != self.local:
            self.local = current
            self.rebuild()
            self.app.sender.update_config(self.app._config)
            self.app.server.rearm_return()
        self.send({"action": "inventory", "screens": self.local})

    def refresh(self):
        try:
            self.local = desktop_win.displays()
        except (OSError, RuntimeError):
            self.status.setText("Windows could not read the screens. Try Refresh screens.")
            return
        self.rebuild()
        self.announce()

    def rebuild(self, reset=False):
        saved = {} if reset or self.app._config is None else {(s["owner"], s["id"]): s for s in self.app._config.screen_layout}
        self.scene.clear()
        right = max((s["x"]+s["width"] for s in self.local), default=0)
        peer_left = min((s["x"] for s in self.peer), default=0)
        for owner, screens in (("local", self.local), ("peer", self.peer)):
            for number, screen in enumerate(screens, 1):
                entry = dict(screen, owner=owner)
                position = saved.get((owner, screen["id"]), dict(screen, x=screen["x"]+(right-peer_left if owner == "peer" else 0)))
                tile = ScreenTile(entry, number)
                self.scene.addItem(tile)
                text = self.scene.addText(f'{"This PC" if owner == "local" else "Other PC"} · {number}\n{screen["id"]}')
                text.setDefaultTextColor(QColor("white"))
                text.setScale(min(8, max(1, (screen["width"]-140)/text.boundingRect().width())))
                text.setParentItem(tile)
                text.setPos(70, 70)
                text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                tile.setPos(position["x"], position["y"])
        self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-150, -150, 150, 150), Qt.AspectRatioMode.KeepAspectRatio)
        self.status.setText(f"{len(self.local)} screen(s) on this PC · {len(self.peer)} on the other PC")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "scene"):
            self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-150, -150, 150, 150), Qt.AspectRatioMode.KeepAspectRatio)

    def reset_layout(self):
        self.rebuild(reset=True)

    def apply(self):
        config = self.app._config
        if config is None or not self.supported() or not self.peer:
            self.status.setText("Connect both PCs before applying a layout.")
            return
        layout = [dict(tile.screen, x=round(tile.x()), y=round(tile.y()))
                  for tile in self.scene.items() if isinstance(tile, ScreenTile)]
        layout = layout_model.validate_layout(layout)
        if layout_model.overlapping(layout):
            self.status.setText("Screens cannot overlap. Drag them apart until their edges touch.")
            return
        if not layout_model.contacts(layout):
            self.status.setText("Make an edge of this PC touch an edge of the other PC first.")
            return
        previous = config.screen_layout
        config.screen_layout = layout
        if not self.app._persist():
            config.screen_layout = previous
            self.status.setText("The layout could not be saved. Check the configuration folder.")
            return
        if not self.send({"action": "layout", "screens": layout_model.reverse_layout(layout)}):
            config.screen_layout = previous
            self.app._persist()
            self.status.setText("The other PC is disconnected. Reconnect before applying.")
            return
        self.app.sender.update_config(config)
        self.app.server.rearm_return()
        self.status.setText("Layout saved on this PC and sent to the other PC.")

    def receive(self, data):
        if not self.supported() or not isinstance(data, dict):
            return
        try:
            action = data.get("action")
            if action == "inventory":
                peer = layout_model.inventory(data.get("screens"))
                if peer != self.peer:
                    self.peer = peer
                    self.app.sender.peer_displays = peer
                    self.app.sender.update_config(self.app._config)
                    self.rebuild()
            elif action == "identify":
                self.show_numbers(data.get("id"))
            elif action == "layout":
                layout = layout_model.validate_layout(data.get("screens"))
                if layout_model.overlapping(layout):
                    return
                # Never accept layouts that name a nonexistent local monitor.
                if {s["id"] for s in layout if s["owner"] == "local"} != {s["id"] for s in self.local}:
                    return
                self.app._config.screen_layout = layout
                if not self.app._persist():
                    self.status.setText("The received layout could not be saved.")
                    return
                self.app.sender.update_config(self.app._config)
                self.app.server.rearm_return()
                self.rebuild()
            elif action == "mode" and isinstance(data.get("enabled"), bool):
                enabled = data["enabled"]
                self.app._config.advanced_crossing = enabled
                self.app.advanced_switch.blockSignals(True)
                self.app.advanced_switch.setChecked(enabled)
                self.app.advanced_switch.blockSignals(False)
                self.setVisible(enabled)
                self.app.basic_ways.setVisible(not enabled)
                self.app._persist()
                self.app.sender.update_config(self.app._config)
                self.app.server.rearm_return()
        except (ValueError, TypeError):
            self.status.setText("The other PC sent an invalid screen layout.")

    def identify(self):
        selected = [s for s in self.scene.selectedItems() if isinstance(s, ScreenTile)]
        if selected:
            screen = selected[0].screen
            if screen["owner"] == "local":
                self.show_numbers(screen["id"])
            elif not self.send({"action": "identify", "id": screen["id"]}):
                self.status.setText("The other PC is disconnected.")
        else:
            self.show_numbers(None)
            self.send({"action": "identify"})

    def show_numbers(self, screen_id):
        # Local displays only, five seconds, GUI thread. Never steals keyboard focus.
        for label in self.labels:
            label.close()
        self.labels = []
        numbers = {s["id"]: i for i, s in enumerate(self.local, 1)}
        for screen in QApplication.screens():
            if screen_id is not None and screen.name() != screen_id:
                continue
            label = QLabel(f'This PC · {numbers.get(screen.name(), "?")}\n{screen.name()}')
            label.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
            label.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background: #17283c; color: white; font-size: 36px; padding: 24px; border: 3px solid #6ca7ff;")
            label.adjustSize()
            centre = screen.geometry().center()
            label.move(centre.x()-label.width()//2, centre.y()-label.height()//2)
            label.show()
            QTimer.singleShot(5000, label.close)
            self.labels.append(label)
