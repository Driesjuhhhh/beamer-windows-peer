"""Live previews for the Design page: the notch and edge animations, played in the settings window by
the very classes that draw them on screen, so a preview cannot drift from the real thing.

Each renderer is hosted in a view rather than a screen-level panel. Only where it draws, and how it
is shown and hidden, is redirected; everything else runs as it does on screen. PreviewFeed stands in
for the controller: the live settings, so a change shows at once, with a scripted push instead of a
trackpad. The script builds pressure, goes through, keeps animating for the chosen time and rests,
on a loop, and PreviewLoop only runs it while the Design page is showing.

Main thread only. A failing preview disables itself as the real renderer does; nothing depends on it.
"""

import time
import types

import AppKit
import Quartz
import objc
import rumps

import crossing
import notch_island
import theme

PUSH_S = 1.8
REST_S = 1.0
FALLBACK_NOTCH = (185.0, 32.0)


def preview_frame(elapsed, after):
    """(pressure, phase) `elapsed` seconds into the loop: pressure builds for PUSH_S and goes
    through, the crossing plays for `after` seconds, then everything rests for REST_S and it starts
    again. Phases are push, after and rest."""
    t = elapsed % (PUSH_S + after + REST_S)
    if t < PUSH_S:
        return (t / PUSH_S) ** 1.6, "push"
    return 0.0, "after" if t < PUSH_S + after else "rest"


def notch_size():
    """This Mac's notch as (width, height), or a typical MacBook's when it has none at the top of
    the desktop, so the Notch previews still show what the styles look like."""
    try:
        geometry = notch_island.notch_geometry()
    except Exception:
        geometry = None
    if geometry is None:
        return FALLBACK_NOTCH
    left, right, _top, height = geometry
    return (right - left, height)


class PreviewFeed:
    """What a hosted renderer reads from its controller. `overrides` pins crossing settings for one
    preview, such as the style a tile shows, while the rest follow the live settings."""

    def __init__(self, controller, **overrides):
        self.controller = controller
        self.overrides = overrides
        self.level = 0.0
        self.crossing = types.SimpleNamespace(touching=False)

    @property
    def cfg(self):
        cfg = self.controller.cfg
        if not self.overrides:
            return cfg
        return types.SimpleNamespace(crossing=dict(cfg.crossing, **self.overrides))

    def crossing_pressure_now(self):
        return self.level


class _Panel:
    """The panel calls the renderers make, answered by a view in the settings window."""

    def __init__(self, view, set_hidden):
        self.view = view
        self.set_hidden = set_hidden

    def contentView(self):
        return self.view

    def backingScaleFactor(self):
        window = self.view.window()
        return window.backingScaleFactor() if window is not None else 2.0

    def setFrame_display_(self, frame, _display):
        self.view.setFrame_(frame)

    def orderFrontRegardless(self):
        self.set_hidden(False)

    def orderOut_(self, _sender):
        self.set_hidden(True)


def hosted_notch(base):
    """NotchBeam or NotchIsland, drawing into a PreviewScreen instead of over the notch."""

    class HostedNotch(base):
        def __init__(self, feed, logger, screen):
            super().__init__(feed, logger)
            self.screen = screen

        def _show(self):
            if self.panel is None:
                width, height = self.screen.notch
                self._build((0.0, width, 0.0, height))
            self.panel.orderFrontRegardless()
            self.visible = True
            return True

        def _panel(self, frame):
            stage = Quartz.CALayer.layer()
            stage.setBounds_(((0.0, 0.0), (frame.size.width, frame.size.height)))
            stage.setGeometryFlipped_(True)
            stage.setAnchorPoint_((0.5, 1.0))
            self.screen.hold(stage)
            return _Panel(self.screen, stage.setHidden_), stage

    return HostedNotch


def hosted_edge(base):
    """The app's EdgeGlow, drawing its band along the right side of a PreviewScreen."""

    class HostedEdge(base):
        def __init__(self, feed, logger, screen):
            super().__init__(feed, logger)
            self.screen = screen

        def _ensure_panel(self):
            if self.panel is not None:
                return
            band = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 1, 1))
            band.setWantsLayer_(True)
            self.screen.addSubview_(band)
            self.fill = Quartz.CAGradientLayer.layer()
            band.layer().addSublayer_(self.fill)
            self.comet = Quartz.CAGradientLayer.layer()
            self.panel = _Panel(band, band.setHidden_)

        def _band_frame(self, band):
            bounds = self.screen.bounds()
            return AppKit.NSMakeRect(bounds.size.width - band, 0, band, bounds.size.height)

    return HostedEdge


class PreviewScreen(AppKit.NSView):
    """The little desktop a preview plays on: a wallpaper-toned ground so a black notch tab reads
    against it and, for a notch preview, the notch itself drawn over whatever the renderer puts
    there, as the hardware covers it. The renderer's stage is scaled so the notch takes about 60% of
    the width, and never larger than life."""

    def layout(self):
        objc.super(PreviewScreen, self).layout()
        self.arrange()

    @objc.python_method
    def setup(self, notch=None):
        self.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self.setWantsLayer_(True)
        layer = self.layer()
        layer.setCornerRadius_(theme.RADIUS["field"])
        layer.setMasksToBounds_(True)
        layer.setBorderWidth_(1)
        layer.setBorderColor_(theme.colour("rule").CGColor())
        self.ground = Quartz.CAGradientLayer.layer()
        self.ground.setColors_([theme.colour("edge").CGColor(), theme.colour("well").CGColor()])
        self.ground.setStartPoint_((0.5, 1.0))
        self.ground.setEndPoint_((0.5, 0.0))
        layer.addSublayer_(self.ground)
        self.notch = notch
        self.stage = None
        self.cutout = None
        if notch is not None:
            self.cutout = Quartz.CAShapeLayer.layer()
            self.cutout.setFillColor_(AppKit.NSColor.blackColor().CGColor())
            layer.addSublayer_(self.cutout)
        return self

    @objc.python_method
    def hold(self, stage):
        if self.stage is not None:
            self.stage.removeFromSuperlayer()
        self.stage = stage
        if self.cutout is not None:
            self.layer().insertSublayer_below_(stage, self.cutout)
        else:
            self.layer().addSublayer_(stage)
        self.arrange()

    @objc.python_method
    def arrange(self):
        if getattr(self, "ground", None) is None:
            return
        bounds = self.bounds()
        width, height = bounds.size.width, bounds.size.height
        scale = min(1.0, width * 0.6 / self.notch[0]) if self.notch is not None else 1.0
        Quartz.CATransaction.begin()
        Quartz.CATransaction.setDisableActions_(True)
        try:
            self.ground.setFrame_(bounds)
            if self.stage is not None:
                self.stage.setPosition_((width / 2.0, height))
                self.stage.setAffineTransform_(Quartz.CGAffineTransformMakeScale(scale, scale))
            if self.cutout is not None:
                notch_width, notch_height = self.notch[0] * scale, self.notch[1] * scale
                radius = 7.0 * scale
                # Taller than the notch by its radius, so only the bottom corners show rounded.
                rect = ((width / 2.0 - notch_width / 2.0, height - notch_height), (notch_width, notch_height + radius))
                self.cutout.setPath_(Quartz.CGPathCreateWithRoundedRect(rect, radius, radius, None))
        finally:
            Quartz.CATransaction.commit()


class PreviewLoop:
    """Plays every preview on the page from one clock, and only while it is wanted."""

    def __init__(self, controller):
        self.controller = controller
        self.players = []
        self.started_at = None
        self.phase = None
        self.quarter = 0
        self.timer = rumps.Timer(self._tick, 1 / 30)

    def add(self, feed, renderer, update):
        """`update(kind, pressure)` passes an event to `renderer` the way the app's crossing
        feedback would."""
        self.players.append((feed, renderer, update))

    def start(self):
        if self.started_at is not None:
            return
        self.started_at = time.monotonic()
        self.phase = None
        self.quarter = 0
        self.timer.start()

    def stop(self):
        if self.started_at is None:
            return
        self.started_at = None
        self.timer.stop()
        for feed, renderer, _update in self.players:
            feed.level = 0.0
            feed.crossing.touching = False
            try:
                renderer._hide()
                renderer.timer.stop()
            except Exception:
                pass

    def _tick(self, _timer):
        if self.started_at is None:
            return
        after = self.controller.cfg.crossing["notch_after_ms"] / 1000.0
        level, phase = preview_frame(time.monotonic() - self.started_at, after)
        quarter = min(3, int(4 * level)) if phase == "push" else 0
        crossed = phase == "after" and self.phase == "push"
        ticked = quarter > self.quarter
        self.phase, self.quarter = phase, quarter
        for feed, _renderer, update in self.players:
            feed.level = level
            feed.crossing.touching = phase == "push"
            if crossed:
                update("cross", 1.0)
            elif phase == "push" and level > 0.0:
                update("tick" if ticked else "pressure", level)


def edge_update(renderer):
    step = crossing.Step
    return lambda kind, level: renderer.update(kind, step(pressure=level, mac_edge="right", region=(0, 0, 1, 1)))


def notch_update(renderer):
    return lambda kind, _level: renderer.update(kind)
