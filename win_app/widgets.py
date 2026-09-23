"""The Vernier components the receiver window draws that a stylesheet cannot: module, eyebrow,
LED, the 60-segment countdown and the switch."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
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

    def __init__(self, pages, on_select, parent: QWidget | None = None) -> None:
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
        outer.addLayout(list_layout)

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
