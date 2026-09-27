"""The Vernier components the receiver window draws that a stylesheet cannot: module, eyebrow,
LED, the 60-segment countdown and the switch."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import theme
import tokens


def label(text: str, role: str, wrap: bool = False) -> QLabel:
    item = QLabel(text)
    item.setProperty("vernier", role)
    item.setWordWrap(wrap)
    return item


def set_role(widget: QWidget, role: str) -> None:
    if widget.property("vernier") != role:
        widget.setProperty("vernier", role)
        theme.repolish(widget)


class Eyebrow(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("vernier", "eyebrow")
        self.setFont(theme.eyebrow_font())


class Module(QFrame):
    """One `panel` cell in the rack, eyebrow first."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("vernier", "module")
        self.body = QVBoxLayout(self)
        vertical, horizontal = (round(v) for v in tokens.MODULE_PADDING)
        self.body.setContentsMargins(horizontal, vertical, horizontal, horizontal)
        self.body.setSpacing(12)
        self.eyebrow = Eyebrow(title)
        self.body.addWidget(self.eyebrow)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)


class Led(QWidget):
    def __init__(self, tone: str = "off", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tone = tone
        self.setFixedSize(QSize(8, 8))

    def set_tone(self, tone: str) -> None:
        if tone != self.tone:
            self.tone = tone
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.colour(self.tone)))
        painter.drawEllipse(0, 0, 8, 8)


class Drain(QWidget):
    """Sixty segments, one per second of the code's life, emptying left to right in `rule`."""

    SEGMENTS = 60

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.remaining = 0
        self.setFixedHeight(12)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_remaining(self, seconds: int) -> None:
        seconds = max(0, min(self.SEGMENTS, int(seconds)))
        if seconds != self.remaining:
            self.remaining = seconds
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        gap = 1.0
        width = (self.width() - gap * (self.SEGMENTS - 1)) / self.SEGMENTS
        lit, spent = QColor(theme.colour("signal")), QColor(theme.colour("rule"))
        for index in range(self.SEGMENTS):
            painter.fillRect(
                QRectF(index * (width + gap), 0, width, self.height()),
                lit if index < self.remaining else spent,
            )


def rule(vertical: bool = True) -> QWidget:
    """A one-pixel divider in `rule`, the sidebar/content seam or a horizontal seam under it."""
    widget = QWidget()
    widget.setProperty("vernier", "rule")
    if vertical:
        widget.setFixedWidth(1)
    else:
        widget.setFixedHeight(1)
    return widget


class Choice:
    """A row of exclusive Vernier choice buttons, `columns` wide. Pick a divisor of
    `len(items)` so a wrap never orphans one. `on_change(value)` fires only on a real
    click -- never on `set_value`, so refreshing from an incoming setting cannot loop back."""

    def __init__(self, items, columns: int, current: str, on_change=None, parent: QWidget | None = None) -> None:
        self.view = QWidget(parent)
        self.view.setProperty("vernier", "plain")
        grid = QGridLayout(self.view)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self._buttons: dict = {}
        for index, (value, text) in enumerate(items):
            button = QPushButton(text)
            button.setProperty("vernier", "choice")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(value == current)
            if on_change is not None:
                button.clicked.connect(lambda _checked=False, v=value: on_change(v))
            grid.addWidget(button, index // columns, index % columns)
            self._buttons[value] = button

    @property
    def value(self):
        return next((value for value, button in self._buttons.items() if button.isChecked()), None)

    def set_value(self, value) -> None:
        button = self._buttons.get(value)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_enabled(self, enabled: bool) -> None:
        for button in self._buttons.values():
            button.setEnabled(enabled)


class _Tile(QFrame):
    """One tile of ChoiceTiles: the whole tile is the control, by click or by Space from Tab."""

    def __init__(self, choose, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._choose = choose
        self.setProperty("vernier", "tile")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._choose()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._choose()
            return
        super().keyPressEvent(event)


class ChoiceTiles:
    """One of several, as tiles side by side: each a live preview over its name and a line saying
    what it is. The chosen tile takes a 2px ink border. `on_change(value)` fires only on a real
    choice, never on `set_value`."""

    def __init__(self, items, current, on_change=None, parent: QWidget | None = None) -> None:
        self.on_change = on_change
        self.value = None
        self.view = QWidget(parent)
        self.view.setProperty("vernier", "plain")
        row = QHBoxLayout(self.view)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._tiles: dict = {}
        for value, title, detail, preview in items:
            tile = _Tile(lambda v=value: self._chosen(v))
            tile.setAccessibleName(title)
            column = QVBoxLayout(tile)
            column.setContentsMargins(8, 8, 8, 12)
            column.setSpacing(6)
            column.addWidget(preview)
            column.addSpacing(4)
            column.addWidget(label(title, "tile-name"))
            column.addWidget(label(detail, "small", wrap=True))
            column.addStretch(1)
            row.addWidget(tile, 1)
            self._tiles[value] = tile
        self.set_value(current)

    def set_value(self, value) -> None:
        self.value = value
        for candidate, tile in self._tiles.items():
            set_role(tile, "tile-on" if candidate == value else "tile")

    def set_enabled(self, enabled: bool) -> None:
        # Faded whole, previews included, as the Mac's tiles are.
        fade = QGraphicsOpacityEffect(self.view)
        fade.setOpacity(1.0 if enabled else 0.45)
        self.view.setGraphicsEffect(None if enabled else fade)
        for tile in self._tiles.values():
            tile.setEnabled(enabled)

    def _chosen(self, value) -> None:
        if value == self.value:
            return
        self.set_value(value)
        if self.on_change is not None:
            self.on_change(value)


class _Swatch(QPushButton):
    CHIP = 24

    def __init__(self, colours, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.colours = list(colours) * (2 if len(colours) == 1 else 1)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.setFixedHeight(self.CHIP + 24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(max(56, self.fontMetrics().horizontalAdvance(self.text()) + 8), self.CHIP + 24)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        chosen = self.isChecked()
        enabled = self.isEnabled()
        chip = QRectF(3, 3, self.width() - 6, self.CHIP)
        gradient = QLinearGradient(chip.left(), 0, chip.right(), 0)
        for index, value in enumerate(self.colours):
            gradient.setColorAt(index / (len(self.colours) - 1), QColor(value))
        painter.setOpacity(1.0 if enabled else 0.45)
        painter.setBrush(gradient)
        ring = "ink" if chosen and enabled else "rule"
        painter.setPen(QPen(QColor(theme.colour(ring)), 2 if chosen else 1))
        radius = tokens.RADIUS["field"]
        painter.drawRoundedRect(chip, radius, radius)
        if self.hasFocus():
            painter.setPen(QPen(QColor(theme.colour("signal")), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(chip.adjusted(-2.5, -2.5, 2.5, 2.5), radius + 2, radius + 2)
        painter.setPen(QColor(theme.colour("ink" if chosen else "ink_2")))
        face = theme.font(tokens.TYPE["small"], 600 if chosen else 400)
        painter.setFont(face)
        painter.drawText(
            QRectF(0, chip.bottom() + 4, self.width(), self.height() - chip.bottom() - 4),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self.text(),
        )


class Swatches:
    """One colour of several from tokens.PALETTES: a chip of each palette's gradient over its name,
    the chosen chip ringed in ink."""

    def __init__(self, items, current, on_change=None, parent: QWidget | None = None) -> None:
        self.view = QWidget(parent)
        self.view.setProperty("vernier", "plain")
        row = QHBoxLayout(self.view)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._swatches: dict = {}
        for value, title in items:
            swatch = _Swatch(tokens.PALETTES[value], title)
            swatch.setChecked(value == current)
            if on_change is not None:
                swatch.clicked.connect(lambda _checked=False, v=value: on_change(v))
            row.addWidget(swatch, 1)
            self._swatches[value] = swatch

    @property
    def value(self):
        return next((value for value, swatch in self._swatches.items() if swatch.isChecked()), None)

    def set_value(self, value) -> None:
        swatch = self._swatches.get(value)
        if swatch is not None and not swatch.isChecked():
            swatch.setChecked(True)

    def set_enabled(self, enabled: bool) -> None:
        for swatch in self._swatches.values():
            swatch.setEnabled(enabled)


class InputRecorder(QPushButton):
    """A keycap that records the next key or mouse button pressed. Clicking arms it; while armed an
    application-wide filter takes the next key or non-left button and hands `on_record` a
    ("key", virtual key) or ("button", name) pair, and a left click anywhere disarms it. The key is
    read as the low-level hook will report it, so what is recorded is what the hook matches."""

    HINT = "Click, then press it"
    RECORDING_HINT = "Click again to cancel"
    BUTTONS = {
        Qt.MouseButton.RightButton: "right",
        Qt.MouseButton.MiddleButton: "middle",
        Qt.MouseButton.BackButton: "back",
        Qt.MouseButton.ForwardButton: "forward",
    }

    def __init__(self, title: str, on_record, hook_vk, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.on_record = on_record
        self.hook_vk = hook_vk
        self.armed = False
        self.setProperty("vernier", "keycap")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.setFixedHeight(42)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(10)
        self.key = label(title, "keycap")
        self.key.setFont(theme.mono_font(tokens.TYPE["field_mono"]))
        self.hint = label(self.HINT, "small")
        for part in (self.key, self.hint):
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.key, 1)
        row.addWidget(self.hint, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.clicked.connect(self._toggle)

    def cancel(self) -> None:
        if not self.armed:
            return
        self.armed = False
        QApplication.instance().removeEventFilter(self)
        self.key.setText(self.title)
        set_role(self.key, "keycap")
        self.hint.setText(self.HINT)
        set_role(self, "keycap")

    def _toggle(self) -> None:
        if self.armed:
            self.cancel()
            return
        self.armed = True
        self.key.setText("Press a key or button…")
        set_role(self.key, "keycap-live")
        self.hint.setText(self.RECORDING_HINT)
        set_role(self, "keycap-live")
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if not self.armed:
            return False
        kind = event.type()
        if kind == QEvent.Type.KeyPress:
            vk = self.hook_vk(event.nativeVirtualKey(), event.nativeScanCode())
            if not vk:
                return True
            self.cancel()
            self.on_record("key", vk)
            return True
        if kind == QEvent.Type.KeyRelease:
            return True
        if kind == QEvent.Type.MouseButtonPress:
            name = self.BUTTONS.get(event.button())
            if name is None:
                # The left button disarms, and the press goes where it was aimed -- except onto
                # this keycap, where it would arm it again.
                inside = isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched))
                self.cancel()
                return inside
            self.cancel()
            self.on_record("button", name)
            return True
        return False


class PageButton(QPushButton):
    """One entry in the sidebar's page list, with an optional tone dot for a page that
    needs attention."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("vernier", "page")
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dot = None

    def set_dot(self, tone: str | None) -> None:
        if tone != self._dot:
            self._dot = tone
            self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._dot is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.colour(self._dot)))
        size = 6
        painter.drawEllipse(QRectF(self.width() - size - 10, (self.height() - size) / 2, size, size))


class Sidebar(QWidget):
    """The page list, with the link state pinned above it. `on_select(key)` fires on a
    click; the window drives `select`/`set_link`/`set_dots` the rest of the time."""

    def __init__(self, pages, on_select, foot: str = "", on_foot=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("vernier", "sidebar")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        link = QWidget()
        link.setProperty("vernier", "plain")
        link_layout = QHBoxLayout(link)
        link_layout.setContentsMargins(16, 16, 16, 16)
        link_layout.setSpacing(8)
        self.link_led = Led()
        link_layout.addWidget(self.link_led, 0, Qt.AlignmentFlag.AlignVCenter)
        self.link_word = label("", "sidebar-link")
        link_layout.addWidget(self.link_word, 1)
        outer.addWidget(link)
        outer.addWidget(rule(vertical=False))

        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(8, 8, 8, 8)
        list_layout.setSpacing(2)
        self._buttons: dict = {}
        for key, name, _purpose in pages:
            button = PageButton(name)
            button.clicked.connect(lambda _checked=False, k=key: on_select(k))
            list_layout.addWidget(button)
            self._buttons[key] = button
        list_layout.addStretch(1)
        outer.addLayout(list_layout, 1)
        if foot:
            # The version and the way back to Beamer's page: one quiet line, never a control
            # anyone has to look past to reach a setting.
            self.foot = QPushButton(foot)
            self.foot.setProperty("vernier", "foot")
            self.foot.setCursor(Qt.CursorShape.PointingHandCursor)
            self.foot.setToolTip("Open in your browser")
            if on_foot is not None:
                self.foot.clicked.connect(on_foot)
            outer.addWidget(self.foot)

    def select(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_link(self, tone: str, word: str) -> None:
        self.link_led.set_tone(tone)
        if self.link_word.text() != word:
            self.link_word.setText(word)

    def set_dots(self, marks: dict) -> None:
        for key, button in self._buttons.items():
            button.set_dot(marks.get(key))


class Switch(QCheckBox):
    """A QCheckBox drawn as Vernier's switch: label left, track right."""

    TRACK = QSize(34, 18)

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(24)

    def sizeHint(self) -> QSize:
        text = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(text + 12 + self.TRACK.width() + 4, max(24, self.TRACK.height() + 6))

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QRectF(
            self.width() - self.TRACK.width() - 2.5,
            (self.height() - self.TRACK.height()) / 2 + 0.5,
            self.TRACK.width(),
            self.TRACK.height() - 1,
        )
        if self.hasFocus():
            painter.setPen(QColor(theme.colour("signal")))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), 11, 11)
        painter.setPen(QColor(theme.colour("signal" if on else "edge")))
        painter.setBrush(QColor(theme.colour("well")))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.colour("signal" if on else "ink_3")))
        knob = 12.0
        x = track.right() - knob - 2.5 if on else track.left() + 2.5
        painter.drawEllipse(QRectF(x, track.center().y() - knob / 2, knob, knob))
        painter.setPen(QColor(theme.colour("ink")))
        painter.setFont(self.font())
        text_rect = QRectF(0, 0, track.left() - 12, self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
