"""The Windows half of the edge glow, along the return edge, on the monitor that owns it. Click-through,
never focused, above other windows.

Two styles, chosen in this app's own settings with a colour: `glow` is a band whose depth and opacity
track pressure with a flash at breakthrough; `beam` is a thin line along the edge with a comet of
light travelling it, faster as the push builds, the whole edge flashing at breakthrough and the comet
running on off the end rather than stopping where it was, after the Mac's notch beam.

Every frame paints the palette along the edge, then cuts it with alpha masks: a falloff inward from
the edge, and for the beam a profile along it. `signal` with `glow` is the original look.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QWidget

import return_edge as crossing
import tokens

BAND_PX = 44
FLASH_SECONDS = tokens.SPRING["flash_seconds"]
STALE_SECONDS = 0.08

COMET = 0.3
BEAM_BASE = 0.2
BEAM_FALLOFF = ((0.0, 1.0), (0.08, 0.85), (0.3, 0.25), (1.0, 0.0))
SLOW_TRAVERSE_S = 2.4
FAST_TRAVERSE_S = 0.8
FINISH_SECONDS = 0.6
FINISH_TRAVERSE_S = 0.35
PROFILE_SAMPLES = 24


def traverse_seconds(strength: float) -> float:
    """One run of the comet along the whole edge: unhurried at a light lean, quick near breakthrough."""
    strength = max(0.0, min(1.0, strength))
    return SLOW_TRAVERSE_S + (FAST_TRAVERSE_S - SLOW_TRAVERSE_S) * strength


def comet_alpha(position: float, centre: float, flash: float) -> float:
    """How lit the edge is at `position` (0 to 1 along it) with the comet's head at `centre`: a dim
    base everywhere, raised to `flash` at breakthrough, and a peak that falls away over half the
    comet's length either side."""
    base = max(BEAM_BASE, min(1.0, flash))
    reach = max(0.0, 1.0 - abs(position - centre) / (COMET / 2.0))
    return base + (1.0 - base) * reach * reach


class EdgeGlow(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._edge = "left"
        self._style = "glow"
        self._colour = "signal"
        self._pressure = 0.0
        self._flash = 0.0
        self._finish = 0.0
        self._centre = -COMET / 2.0
        self._updated_at = 0.0
        self._ticked_at = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def configure(self, style: str, colour: str) -> None:
        self._style = style
        self._colour = colour

    def set_pressure(self, edge: str, pressure: float, crossed: bool) -> None:
        now = time.monotonic()
        if edge != self._edge or self.isHidden():
            self._edge = edge
            self._place()
        self._pressure = 0.0 if crossed else max(0.0, min(1.0, pressure))
        if crossed:
            self._flash = 1.0
            self._finish = 1.0
        self._updated_at = now
        if self.isHidden():
            self._ticked_at = now
            self._centre = -COMET / 2.0
            self.show()
            self._timer.start()
        self.update()

    def _place(self) -> None:
        screens = QApplication.screens()
        if not screens:
            return
        rects = [crossing.Rect(s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height()) for s in screens]
        owner = crossing.owning_monitor(rects, self._edge)
        if self._edge == "left":
            self.setGeometry(QRect(owner.x, owner.y, BAND_PX, owner.height))
        elif self._edge == "right":
            self.setGeometry(QRect(owner.right - BAND_PX + 1, owner.y, BAND_PX, owner.height))
        elif self._edge == "top":
            self.setGeometry(QRect(owner.x, owner.y, owner.width, BAND_PX))
        else:
            self.setGeometry(QRect(owner.x, owner.bottom - BAND_PX + 1, owner.width, BAND_PX))

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed = now - self._ticked_at
        self._ticked_at = now
        # The model only decays when a delta arrives, so once the push stops
        # the glow fades on its own clock, matching the model's 400ms.
        if now - self._updated_at > STALE_SECONDS:
            self._pressure = max(0.0, self._pressure - elapsed / crossing.DECAY_SECONDS)
        self._flash = max(0.0, self._flash - elapsed / FLASH_SECONDS)
        if self._finish > 0.0:
            # Run on off the end of the edge instead of stopping, and never wrap back to the start.
            self._centre = min(1.0 + COMET, self._centre + elapsed / FINISH_TRAVERSE_S)
            self._finish = max(0.0, self._finish - elapsed / FINISH_SECONDS)
        else:
            self._centre += elapsed / traverse_seconds(self._pressure)
            if self._centre > 1.0 + COMET / 2.0:
                self._centre = -COMET / 2.0
        if self._pressure <= 0.0 and self._flash <= 0.0 and self._finish <= 0.0:
            self._timer.stop()
            self.hide()
            return
        self.update()

    def paintEvent(self, _event) -> None:
        beam = self._style == "beam"
        strength = max(self._pressure * 0.85, self._flash, self._finish if beam else 0.0)
        if strength <= 0.0:
            return
        along = self._edge in ("left", "right")
        length = self.height() if along else self.width()
        painter = QPainter(self)
        painter.setOpacity(strength)
        painter.fillRect(self.rect(), self._colours(along, length))
        painter.setOpacity(1.0)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        if beam:
            painter.fillRect(self.rect(), self._falloff(BAND_PX, BEAM_FALLOFF))
            painter.fillRect(self.rect(), self._comet(along, length))
        else:
            depth = BAND_PX * (0.35 + 0.65 * max(self._pressure, self._flash))
            painter.fillRect(self.rect(), self._falloff(depth, ((0.0, 1.0), (1.0, 0.0))))
        painter.end()

    def _gradient_along(self, along: bool, length: int) -> QLinearGradient:
        return QLinearGradient(0, 0, 0, length) if along else QLinearGradient(0, 0, length, 0)

    def _colours(self, along: bool, length: int) -> QLinearGradient:
        gradient = self._gradient_along(along, length)
        palette = tokens.PALETTES.get(self._colour, tokens.PALETTES["signal"])
        if len(palette) == 1:
            palette = palette * 2
        for index, value in enumerate(palette):
            gradient.setColorAt(index / (len(palette) - 1), QColor(value))
        return gradient

    def _falloff(self, depth: float, stops) -> QLinearGradient:
        width, height = self.width(), self.height()
        gradient = {
            "left": lambda: QLinearGradient(0, 0, depth, 0),
            "right": lambda: QLinearGradient(width, 0, width - depth, 0),
            "top": lambda: QLinearGradient(0, 0, 0, depth),
        }.get(self._edge, lambda: QLinearGradient(0, height, 0, height - depth))()
        for at, alpha in stops:
            gradient.setColorAt(at, QColor(0, 0, 0, round(255 * alpha)))
        return gradient

    def _comet(self, along: bool, length: int) -> QLinearGradient:
        gradient = self._gradient_along(along, length)
        for index in range(PROFILE_SAMPLES + 1):
            at = index / PROFILE_SAMPLES
            gradient.setColorAt(at, QColor(0, 0, 0, round(255 * comet_alpha(at, self._centre, self._flash))))
        return gradient
