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

from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

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

# The Design page's scripted push: pressure builds for PUSH_S and goes through, the breakthrough
# plays out, then everything rests before the next one. The Mac's previews run the same script.
PUSH_S = 1.8
AFTER_S = FINISH_SECONDS + 0.4
REST_S = 1.0
PREVIEW_HEIGHT = 96


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


def preview_frame(elapsed: float):
    """(pressure, phase) `elapsed` seconds into the preview's loop; phases are push, after and
    rest."""
    t = elapsed % (PUSH_S + AFTER_S + REST_S)
    if t < PUSH_S:
        return (t / PUSH_S) ** 1.6, "push"
    return 0.0, "after" if t < PUSH_S + AFTER_S else "rest"


class GlowState:
    """What the glow shows at one moment -- the pressure, the breakthrough flash, the beam's run-off
    and where the comet is -- and how it moves on between frames. The screen's glow and the Design
    page's previews both run one, so a preview cannot drift from the real thing."""

    def __init__(self) -> None:
        self.pressure = 0.0
        self.flash = 0.0
        self.finish = 0.0
        self.centre = -COMET / 2.0

    def restart(self) -> None:
        self.centre = -COMET / 2.0

    def push(self, pressure: float, crossed: bool) -> None:
        self.pressure = 0.0 if crossed else max(0.0, min(1.0, pressure))
        if crossed:
            self.flash = 1.0
            self.finish = 1.0

    def step(self, elapsed: float, stale: bool) -> bool:
        """Moves on by `elapsed` seconds and answers whether anything is still lit. `stale` is
        whether the push has stopped arriving, which is when the pressure fades on its own clock."""
        if stale:
            self.pressure = max(0.0, self.pressure - elapsed / crossing.DECAY_SECONDS)
        self.flash = max(0.0, self.flash - elapsed / FLASH_SECONDS)
        if self.finish > 0.0:
            # Run on off the end of the edge instead of stopping, and never wrap back to the start.
            self.centre = min(1.0 + COMET, self.centre + elapsed / FINISH_TRAVERSE_S)
            self.finish = max(0.0, self.finish - elapsed / FINISH_SECONDS)
        else:
            self.centre += elapsed / traverse_seconds(self.pressure)
            if self.centre > 1.0 + COMET / 2.0:
                self.centre = -COMET / 2.0
        return self.pressure > 0.0 or self.flash > 0.0 or self.finish > 0.0


def paint(painter: QPainter, rect: QRect, edge: str, style: str, colour: str, state: GlowState, band: float = BAND_PX) -> None:
    """Draws the glow along `edge` of `rect`, `band` deep: the palette along the edge, cut by a
    falloff inward from it and, for the beam, the comet's profile along it."""
    beam = style == "beam"
    strength = max(state.pressure * 0.85, state.flash, state.finish if beam else 0.0)
    if strength <= 0.0:
        return
    along = edge in ("left", "right")
    length = rect.height() if along else rect.width()
    painter.save()
    painter.translate(rect.topLeft())
    local = QRect(0, 0, rect.width(), rect.height())
    painter.setOpacity(strength)
    painter.fillRect(local, _colours(colour, along, length))
    painter.setOpacity(1.0)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    if beam:
        painter.fillRect(local, _falloff(edge, local, band, BEAM_FALLOFF))
        painter.fillRect(local, _comet(along, length, state))
    else:
        depth = band * (0.35 + 0.65 * max(state.pressure, state.flash))
        painter.fillRect(local, _falloff(edge, local, depth, ((0.0, 1.0), (1.0, 0.0))))
    painter.restore()


def _gradient_along(along: bool, length: int) -> QLinearGradient:
    return QLinearGradient(0, 0, 0, length) if along else QLinearGradient(0, 0, length, 0)


def _colours(colour: str, along: bool, length: int) -> QLinearGradient:
    gradient = _gradient_along(along, length)
    palette = tokens.PALETTES.get(colour, tokens.PALETTES["signal"])
    if len(palette) == 1:
        palette = palette * 2
    for index, value in enumerate(palette):
        gradient.setColorAt(index / (len(palette) - 1), QColor(value))
    return gradient


def _falloff(edge: str, rect: QRect, depth: float, stops) -> QLinearGradient:
    width, height = rect.width(), rect.height()
    gradient = {
        "left": lambda: QLinearGradient(0, 0, depth, 0),
        "right": lambda: QLinearGradient(width, 0, width - depth, 0),
        "top": lambda: QLinearGradient(0, 0, 0, depth),
    }.get(edge, lambda: QLinearGradient(0, height, 0, height - depth))()
    for at, alpha in stops:
        gradient.setColorAt(at, QColor(0, 0, 0, round(255 * alpha)))
    return gradient


def _comet(along: bool, length: int, state: GlowState) -> QLinearGradient:
    gradient = _gradient_along(along, length)
    for index in range(PROFILE_SAMPLES + 1):
        at = index / PROFILE_SAMPLES
        gradient.setColorAt(at, QColor(0, 0, 0, round(255 * comet_alpha(at, state.centre, state.flash))))
    return gradient


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
        self._state = GlowState()
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
        self._state.push(pressure, crossed)
        self._updated_at = now
        if self.isHidden():
            self._ticked_at = now
            self._state.restart()
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
        if not self._state.step(elapsed, now - self._updated_at > STALE_SECONDS):
            self._timer.stop()
            self.hide()
            return
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        paint(painter, self.rect(), self._edge, self._style, self._colour, self._state)
        painter.end()


class GlowPreview(QWidget):
    """A little desktop with the glow playing along the edge that leads to the Mac, painted by the
    same `paint` and `GlowState` as the real one, at its real depth. `style` is fixed per preview;
    the colour and the edge follow the settings."""

    def __init__(self, style: str, colour: str = "signal", edge: str = "right", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.style = style
        self.colour = colour
        self.edge = edge
        self.state = GlowState()
        self.setFixedHeight(PREVIEW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_look(self, colour: str, edge: str) -> None:
        if (colour, edge) != (self.colour, self.edge):
            self.colour, self.edge = colour, edge
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = tokens.RADIUS["field"]
        outline = QPainterPath()
        outline.addRoundedRect(frame, radius, radius)
        ground = QLinearGradient(0, 0, 0, self.height())
        ground.setColorAt(0.0, QColor(tokens.PALETTE["edge"]))
        ground.setColorAt(1.0, QColor(tokens.PALETTE["well"]))
        painter.fillPath(outline, ground)
        # Painted on a layer of its own, as the real glow is on its own window: its masks cut the
        # glow, and on the widget itself they would cut the ground under it too.
        ratio = self.devicePixelRatioF()
        layer = QImage(self.size() * ratio, QImage.Format.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.GlobalColor.transparent)
        layer_painter = QPainter(layer)
        paint(layer_painter, self.rect(), self.edge, self.style, self.colour, self.state)
        layer_painter.end()
        painter.save()
        painter.setClipPath(outline)
        painter.drawImage(0, 0, layer)
        painter.restore()
        painter.setPen(QPen(QColor(tokens.PALETTE["rule"]), 1))
        painter.drawPath(outline)
        painter.end()


class PreviewLoop:
    """Plays every preview from one clock, and only while someone can see them."""

    def __init__(self, parent: QWidget) -> None:
        self.previews: list = []
        self._started_at = None
        self._ticked_at = 0.0
        self._phase = None
        self._timer = QTimer(parent)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def add(self, preview: GlowPreview) -> None:
        self.previews.append(preview)

    def run(self, wanted: bool) -> None:
        if wanted and self._started_at is None:
            self._started_at = self._ticked_at = time.monotonic()
            self._phase = None
            self._timer.start()
        elif not wanted and self._started_at is not None:
            self._started_at = None
            self._timer.stop()
            for preview in self.previews:
                preview.state = GlowState()
                preview.update()

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed, self._ticked_at = now - self._ticked_at, now
        level, phase = preview_frame(now - self._started_at)
        crossed = phase == "after" and self._phase == "push"
        self._phase = phase
        for preview in self.previews:
            if crossed:
                preview.state.push(1.0, True)
            elif phase == "push":
                preview.state.push(level, False)
            preview.state.step(elapsed, phase != "push")
            preview.update()
