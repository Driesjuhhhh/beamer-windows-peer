import argparse
import collections
import fcntl
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import AppKit
import ApplicationServices
import Quartz
import objc
import rumps
from PyObjCTools import AppHelper

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as config_module
import crossing
import gestures
import ignored_titles
import notch_beam
import previews
from notch_beam import NotchBeam
from notch_island import NotchIsland
from bridge import _GestureEventView
from key_codes import KEY_NAME_TO_CODE
import link_state
import login_item
import pages
import protocol
import pairing
from settings_store import (
    SettingsError,
    SettingsStore,
    config_to_raw,
    editable_default_config,
    migrate_legacy_config,
)
import theme
from wake import WakingController, lookup_mac
import widgets
from windows_input import WindowsInput


LOG_DIRECTORY = Path.home() / "Library" / "Logs" / "Beamer"
LOG_PATH = LOG_DIRECTORY / "Beamer.log"
CAPTURE_RETRY_INTERVAL_SECONDS = 5.0
# The repo-root VERSION file is the one place the version is set; py2app copies it into Resources.
try:
    VERSION = (Path(os.environ.get("RESOURCEPATH") or Path(__file__).resolve().parent.parent) / "VERSION").read_text().strip()
except OSError:
    VERSION = "dev"
FULL_SCREEN_CHECK_INTERVAL_SECONDS = 1.0
# The pages switch between their two layouts at this width of the content pane, beside the sidebar.
WIDE_WIDTH = 600.0
# Accessibility description per menu-bar state. "held" is input on this Mac with the pointer ways
# in off, by a pause or a full-screen app.
MENU_BAR_STATES = {
    "local": "Input on this Mac",
    "held": "Input held on this Mac; crossing is off",
    "windows": "Input on Windows",
}


def menu_bar_glyph(state):
    """Vernier's template glyph, 22 by 16pt: two screens, the filled one where input is, a chevron
    pointing at it for the way input went, and for crossing held a solid bar closing the gap
    between two outlines. Drawn in black and marked as a template, so macOS tints it for the bar."""

    def draw(_rect):
        AppKit.NSColor.blackColor().set()
        for x, filled in ((1.0, state == "local"), (13.0, state == "windows")):
            if filled:
                AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((x, 2), (8, 12)), 1.5, 1.5).fill()
            else:
                outline = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((x + 0.75, 2.75), (6.5, 10.5)), 1, 1)
                outline.setLineWidth_(1.5)
                outline.stroke()
        if state == "held":
            AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((10, 0), (2, 16)), 1, 1).fill()
            return True
        tip, tail = (10.0, 12.0) if state == "local" else (12.0, 10.0)
        chevron = AppKit.NSBezierPath.bezierPath()
        chevron.moveToPoint_((tail, 5.5))
        chevron.lineToPoint_((tip, 8.0))
        chevron.lineToPoint_((tail, 10.5))
        chevron.setLineWidth_(1.4)
        chevron.setLineCapStyle_(AppKit.NSLineCapStyleRound)
        chevron.setLineJoinStyle_(AppKit.NSLineJoinStyleRound)
        chevron.stroke()
        return True

    image = AppKit.NSImage.imageWithSize_flipped_drawingHandler_((22, 16), True, draw)
    image.setTemplate_(True)
    image.setAccessibilityDescription_(MENU_BAR_STATES[state])
    return image


def configure_logging():
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(LOG_DIRECTORY, 0o700)
    except OSError:
        pass
    # The handlers go on the root logger, not "Beamer": the shared modules --
    # receiver, return_edge, pairing -- log under their own names, and with
    # the handlers on "Beamer" everything the PC's input did on this Mac went
    # nowhere, which left the 23-09-2026 stranded mouse with no record here.
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    logger = logging.getLogger("Beamer")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH,
        maxBytes=1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)
    return logger


def accessibility_granted():
    return bool(
        ApplicationServices.AXIsProcessTrustedWithOptions(
            {ApplicationServices.kAXTrustedCheckOptionPrompt: False}
        )
    )


def input_monitoring_granted():
    return bool(Quartz.CGPreflightListenEventAccess())


def acquire_instance_lock():
    lock_path = Path.home() / "Library" / "Application Support" / "Beamer" / "Beamer.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


class _GestureCaptureView(AppKit.NSView):
    """Content view for the invisible gesture-capture overlay panel (see
    GestureOverlay below).

    Bug 3: the CGEventTap-based gesture path (bridge.py's
    _handle_gesture_event, fed by private NSEventType 29-32) is best-effort
    and was observed to never fire at all on macOS 27 beta -- no "gesture
    capture active" log line ever appeared. macOS instead routes trackpad
    gestures to whichever window sits directly under the cursor through
    ordinary, fully-supported NSResponder methods. Since Bug 1's cursor pin
    keeps that location fixed while redirecting, placing this (otherwise
    invisible, input-transparent-looking but not actually
    ignoresMouseEvents) panel there lets it receive gestures the normal way
    -- and because this view consumes them, the local Mac gesture no longer
    fires either.

    NOTE: three/four-finger system gestures (Mission Control, Spaces,
    App Exposé) are consumed by the system compositor before any
    application-level responder -- including this one -- ever sees them.
    Nothing running as a normal app can capture those; they remain local to
    the Mac by OS design, regardless of this overlay.
    """

    def magnifyWithEvent_(self, event):
        self._forward(gestures.MAGNIFY_TYPE, event)

    def swipeWithEvent_(self, event):
        self._forward(gestures.SWIPE_TYPE, event)

    def smartMagnifyWithEvent_(self, event):
        # Reserved, like the tap path's SMART_MAGNIFY_TYPE -- overridden
        # only so this doesn't fall through to a default AppKit handler.
        pass

    @objc.python_method
    def _forward(self, event_type, event):
        controller = getattr(self, "controller", None)
        if controller is None:
            return
        try:
            controller.handle_overlay_gesture(event_type, _GestureEventView(event))
        except Exception:
            # handle_overlay_gesture already guards its own body; this is
            # one more layer of "never let a gesture crash the app".
            logging.getLogger("Beamer").exception("overlay gesture forwarding failed")


class GestureOverlay:
    """Owns the invisible NSPanel used to capture trackpad gestures while
    redirecting (see _GestureCaptureView above). Every method here touches
    AppKit and must only ever run on the main thread -- it is driven
    exclusively from TrayApp's periodic status-refresh timer (see
    refresh_status), which already runs there, so no locking is needed.

    Creation is attempted lazily, on first use, and any failure disables the
    overlay permanently for this run: gesture capture then simply falls back
    to whatever the (best-effort, possibly nonfunctional) event tap manages
    -- no crash, no regression versus today's behaviour.
    """

    SIZE = 400.0

    def __init__(self, controller, logger):
        self.controller = controller
        self.logger = logger
        self.panel = None
        self.view = None
        self.visible = False
        self.disabled = False

    def sync(self):
        """Call on every status-refresh tick. Shows the panel, repositioned
        on the controller's current cursor pin point, while redirecting;
        hides it the rest of the time. A show can lag the redirect flip by
        up to one tick of that timer (currently 0.4s), which is acceptable."""
        if self.disabled:
            return
        try:
            if self.controller.redirecting:
                self._show()
            else:
                self._hide()
        except Exception:
            self.disabled = True
            self.logger.exception(
                "gesture-capture overlay failed; falling back to tap-only gesture capture"
            )

    def _ensure_panel(self):
        if self.panel is not None:
            return True
        style = (
            AppKit.NSWindowStyleMaskBorderless
            | AppKit.NSWindowStyleMaskNonactivatingPanel
        )
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, self.SIZE, self.SIZE),
            style,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(AppKit.NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setHasShadow_(False)
        panel.setBackgroundColor_(AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.02))
        panel.setIgnoresMouseEvents_(False)
        panel.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces)
        view = _GestureCaptureView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, self.SIZE, self.SIZE)
        )
        view.controller = self.controller
        panel.setContentView_(view)
        self.panel = panel
        self.view = view
        return True

    def _show(self):
        self._ensure_panel()
        pin = self.controller.cursor_pin_point
        if pin is not None:
            half = self.SIZE / 2.0
            screen = AppKit.NSScreen.mainScreen()
            # CGEventGetLocation reports a top-left-origin Quartz point;
            # AppKit screen coordinates are bottom-left-origin. Flipping
            # against the main screen's height is only exactly right for an
            # un-rotated single-display setup, which is an acceptable
            # approximation for this best-effort overlay -- worst case it's
            # centered a bit off on an unusual multi-display arrangement,
            # not that gestures stop working.
            screen_height = screen.frame().size.height if screen is not None else pin.y * 2
            frame = AppKit.NSMakeRect(pin.x - half, screen_height - pin.y - half, self.SIZE, self.SIZE)
            self.panel.setFrame_display_(frame, False)
        # Never makeKey/makeMain -- this must not steal focus from whatever
        # the user is actually looking at.
        self.panel.orderFrontRegardless()
        self.visible = True

    def _hide(self):
        if self.panel is None or not self.visible:
            return
        self.panel.orderOut_(None)
        self.visible = False


def notch_x_range():
    """The notch's x-range in global points, or None on a Mac without one. Derived from the
    two auxiliary top areas rather than hard-coded, and only when the notched screen forms the
    top of the desktop, because the engine tests it against the top of the bounding box. Only x
    is read, and x is the one axis AppKit and Quartz agree on, so nothing is flipped."""
    screens = AppKit.NSScreen.screens()
    if not screens:
        return None
    desktop_top = max(screen.frame().origin.y + screen.frame().size.height for screen in screens)
    for screen in screens:
        frame = screen.frame()
        if frame.origin.y + frame.size.height != desktop_top:
            continue
        try:
            if screen.safeAreaInsets().top <= 0:
                continue
            left = screen.auxiliaryTopLeftArea()
            right = screen.auxiliaryTopRightArea()
        except AttributeError:
            continue
        if left is None or right is None or left.size.width <= 0 or right.size.width <= 0:
            continue
        return (left.origin.x + left.size.width, right.origin.x)
    return None


def full_screen_app():
    """The frontmost app's name while it is full screen, else None.

    The signal that works is Accessibility's `AXFullScreen` on the frontmost app's focused
    window. Beamer already holds Accessibility for its event tap, so this costs no new
    permission. Measured 10-09-2026 against Chrome driven by the OS's own Enter Full Screen
    shortcut: False windowed, True full screen, False again on leaving.

    ⚠ Three plausible signals were measured and do NOT work, so nobody should try them again:
    `currentSystemPresentationOptions()` stays 0, because that bit is for apps that request
    full-screen presentation explicitly rather than the green button; `NSMenu.menuBarVisible()`
    stays True throughout; and the window server reports a full-screen app's windows as
    fragments (1728x33, 1728x41, 1728x962 ...) rather than one window the size of the display,
    so a bounds comparison never matches. The bounds test is kept only as a fallback for a
    borderless full-screen game, which really is one window sized to the display and may not
    expose AXFullScreen at all.

    ⚠ Also measured: Chrome's AppleScript `fullscreen` property does not enter full screen, and
    believing it does produces a confident wrong answer. Drive the OS shortcut when testing.

    Main thread, once a second."""
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None
    name = app.localizedName() or "An app"
    if _ax_full_screen(app.processIdentifier()):
        return name
    error, displays, count = Quartz.CGGetActiveDisplayList(16, None, None)
    if error != 0:
        raise RuntimeError(f"CGGetActiveDisplayList failed: {error}")
    display_frames = []
    for display in list(displays)[:count]:
        rect = Quartz.CGDisplayBounds(display)
        display_frames.append((rect.origin.x, rect.origin.y, rect.size.width, rect.size.height))
    windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    if _covers_a_display(windows or (), app.processIdentifier(), display_frames):
        return name
    return None


def _ax_full_screen(pid) -> bool:
    """AXFullScreen on that process's focused window. False on any Accessibility error --
    a process with no focused window, or one that exposes no such attribute, is not full
    screen as far as crossing is concerned, and this must never raise into the tap's path."""
    try:
        element = ApplicationServices.AXUIElementCreateApplication(pid)
        error, window = ApplicationServices.AXUIElementCopyAttributeValue(
            element, "AXFocusedWindow", None)
        if error != 0 or window is None:
            return False
        error, value = ApplicationServices.AXUIElementCopyAttributeValue(
            window, "AXFullScreen", None)
        return error == 0 and bool(value)
    except Exception:
        return False


def _covers_a_display(windows, pid, display_frames):
    """Whether that process has an ordinary window sized to a whole display — the borderless
    full-screen game that exposes no AXFullScreen. Both halves of this are load-bearing.

    ⚠ Only layer 0. Finder's desktop window, WindowManager's wallpaper and the window server's
    backstop are all exactly display-sized, so without the layer test clicking the desktop put
    Finder frontmost and switched crossing off.

    ⚠ The window must start at the display's own top and match its full height. There used to be
    slack of the screen's safe-area inset here, for a game that sits under the menu bar; on a
    notched Mac that inset IS the menu bar height, so every ordinary zoomed window (0, 33,
    1728x1084 on this MacBook) matched it and crossing died the moment any other app came
    forward. A game that respects the safe area is indistinguishable from a zoomed window, and
    losing crossing daily is the worse of the two errors."""
    for info in windows:
        if info.get("kCGWindowOwnerPID") != pid or info.get("kCGWindowLayer") != 0:
            continue
        bounds = info.get("kCGWindowBounds") or {}
        for x, y, width, height in display_frames:
            if (
                abs((bounds.get("X") or 0) - x) <= 1
                and abs((bounds.get("Y") or 0) - y) <= 1
                and abs((bounds.get("Width") or 0) - width) <= 1
                and abs((bounds.get("Height") or 0) - height) <= 1
            ):
                return True
    return False


class Haptics:
    """Force Touch trackpad feedback for crossing. A Mac with a mouse or an older trackpad gets
    a performer that does nothing, and any failure switches haptics off for the run rather than
    ever reaching the crossing path."""

    def __init__(self, logger):
        self.logger = logger
        try:
            self.performer = AppKit.NSHapticFeedbackManager.defaultPerformer()
        except Exception:
            self.performer = None
            self.logger.exception("haptic feedback unavailable")

    def tick(self, feel="medium"):
        """`feel` is crossing.haptic_feel: light, medium or firm, macOS's three patterns."""
        self._perform({
            "light": AppKit.NSHapticFeedbackPatternGeneric,
            "firm": AppKit.NSHapticFeedbackPatternLevelChange,
        }.get(feel, AppKit.NSHapticFeedbackPatternAlignment))

    def thud(self):
        self._perform(AppKit.NSHapticFeedbackPatternLevelChange)

    def _perform(self, pattern):
        if self.performer is None:
            return
        try:
            self.performer.performFeedbackPattern_performanceTime_(
                pattern, AppKit.NSHapticFeedbackPerformanceTimeNow
            )
        except Exception:
            self.performer = None
            self.logger.exception("haptic feedback failed; haptics off for this run")


class EdgeGlow:
    """A band along the edge being pushed, in `crossing.glow_colour`: the `glow` style's width and
    opacity track pressure, the `beam` style is a thin line with a comet travelling it that runs on
    off the end at breakthrough, and both flash when the push goes through. The same borderless non-activating panel
    as GestureOverlay, with two differences that matter: it ignores mouse events, or it would
    eat the very push it is drawing, and it joins full-screen spaces as an auxiliary window so
    it sits above a full-screen app.

    Main thread only, like GestureOverlay. Pressure changes arrive through `update`; a timer
    then redraws at 30Hz until both the pressure and the flash have faded, since nothing
    arrives from the tap once the push stops. Any failure disables the glow for the run."""

    BAND_MAX = 18.0
    FLASH_SECONDS = 0.18
    PREVIEW_SECONDS = 0.6

    def __init__(self, controller, logger):
        self.controller = controller
        self.logger = logger
        self.panel = None
        self.fill = None
        self.comet = None
        self.visible = False
        self.disabled = False
        self.mac_edge = None
        self.region = None
        self.flash_at = None
        self.finish = 0.0
        self.centre = -notch_beam.EDGE_COMET / 2.0
        self.drawn_at = None
        self.preview_level = 0.0
        self.preview_until = 0.0
        self.timer = rumps.Timer(self._tick, 1 / 30)

    def update(self, kind, step):
        if self.disabled:
            return
        try:
            if kind == "cross":
                self.flash_at = time.monotonic()
                self.finish = 1.0
            elif kind not in ("pressure", "tick"):
                return
            elif not self.visible:
                self.centre = -notch_beam.EDGE_COMET / 2.0
            self.mac_edge = step.mac_edge
            self.region = step.region
            self._draw()
        except Exception:
            self._fail()

    def preview(self, mac_edge, level):
        """Lights the configured edge at `level` for a moment, for the resistance slider."""
        if self.disabled:
            return
        try:
            bounds = self.controller._current_desktop_bounds()
            self.mac_edge = mac_edge
            self.region = crossing.CrossingEngine._strip(mac_edge, bounds)
            self.preview_level = level
            self.preview_until = time.monotonic() + self.PREVIEW_SECONDS
            self._draw()
        except Exception:
            self._fail()

    def _fail(self):
        self.disabled = True
        self.logger.exception("edge glow failed; glow off for this run")
        try:
            self._hide()
        except Exception:
            pass

    def _tick(self, _timer):
        if self.disabled:
            self.timer.stop()
            return
        try:
            self._draw()
        except Exception:
            self._fail()
            self.timer.stop()

    def _draw(self):
        now = time.monotonic()
        elapsed = 0.0 if self.drawn_at is None else min(0.1, now - self.drawn_at)
        self.drawn_at = now
        feel = self.controller.cfg.crossing
        beam = feel["glow_style"] == "beam"
        level = self.controller.crossing_pressure_now()
        if now < self.preview_until:
            level = max(level, self.preview_level)
        flash = 0.0
        if self.flash_at is not None:
            flash = max(0.0, 1.0 - (now - self.flash_at) / self.FLASH_SECONDS)
            if flash <= 0.0:
                self.flash_at = None
        comet = notch_beam.EDGE_COMET
        if self.finish > 0.0:
            # Run on off the end of the edge instead of stopping, and never wrap back to the start.
            self.centre = min(1.0 + comet, self.centre + elapsed / notch_beam.EDGE_FINISH_TRAVERSE_S)
            self.finish = max(0.0, self.finish - elapsed / notch_beam.EDGE_FINISH_S)
        elif level > 0.0:
            self.centre += elapsed / notch_beam.edge_traverse_seconds(level)
            if self.centre > 1.0 + comet / 2.0:
                self.centre = -comet / 2.0
        lingering = self.finish if beam else 0.0
        if (level <= 0.0 and flash <= 0.0 and lingering <= 0.0) or self.region is None or self.mac_edge is None:
            self._hide()
            self.timer.stop()
            self.drawn_at = None
            return
        self._ensure_panel()
        strength = max(level, flash, lingering)
        band = 3.0 + 3.0 * strength if beam else 2.0 + self.BAND_MAX * strength
        self.panel.setFrame_display_(self._band_frame(band), False)
        # Colour runs along the edge: top to bottom on a side, left to right along the top or bottom.
        start, end = ((0.5, 1.0), (0.5, 0.0)) if self.mac_edge in ("left", "right") else ((0.0, 0.5), (1.0, 0.5))
        Quartz.CATransaction.begin()
        Quartz.CATransaction.setDisableActions_(True)
        try:
            bounds = self.panel.contentView().bounds()
            for layer in (self.fill, self.comet):
                layer.setFrame_(bounds)
                layer.setStartPoint_(start)
                layer.setEndPoint_(end)
            self.fill.setColors_(notch_beam.palette_colours(feel["glow_colour"]))
            if beam:
                stops = [index / 24 for index in range(25)]
                self.comet.setLocations_(stops)
                self.comet.setColors_([
                    AppKit.NSColor.colorWithWhite_alpha_(1.0, notch_beam.edge_comet_alpha(at, self.centre, flash)).CGColor()
                    for at in stops
                ])
                self.fill.setMask_(self.comet)
                self.fill.setOpacity_(min(1.0, strength))
            else:
                self.fill.setMask_(None)
                self.fill.setOpacity_(min(1.0, 0.3 + 0.7 * level + 0.6 * flash))
        finally:
            Quartz.CATransaction.commit()
        if not self.visible:
            self.panel.orderFrontRegardless()
            self.visible = True
        if not getattr(self.timer, "is_alive", lambda: False)():
            self.timer.start()

    def _band_frame(self, band):
        """The band grows inward from the strip the engine reported. Quartz rects are top-left
        origin and AppKit frames bottom-left; the flip is about the primary screen's height,
        which is exact for every arrangement because every screen is placed relative to it."""
        x, y, width, height = self.region
        edge = self.mac_edge
        if width <= crossing.CORNER_PX and height <= crossing.CORNER_PX:
            # A corner box: grow it inward on both axes.
            size = crossing.CORNER_PX + band
            top = self.controller._current_desktop_bounds()[1]
            x = x if edge == "left" else x + width - size
            y = y if y <= top else y + height - size
            width = height = size
        elif edge == "right":
            x, width = x + width - band, band
        elif edge == "left":
            width = band
        elif edge == "top":
            height = band
        else:
            y, height = y + height - band, band
        primary_height = AppKit.NSScreen.screens()[0].frame().size.height
        return AppKit.NSMakeRect(x, primary_height - (y + height), width, height)

    def _ensure_panel(self):
        if self.panel is not None:
            return
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, 1, 1),
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(AppKit.NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setHasShadow_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        view = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 1, 1))
        view.setWantsLayer_(True)
        panel.setContentView_(view)
        self.fill = Quartz.CAGradientLayer.layer()
        view.layer().addSublayer_(self.fill)
        self.comet = Quartz.CAGradientLayer.layer()
        self.panel = panel

    def _hide(self):
        if self.panel is None or not self.visible:
            return
        self.panel.orderOut_(None)
        self.visible = False


BEAMER_SITE_URL = "https://kalkmancode.co.uk/beamer"


def show_about_panel():
    """The standard About panel, with a centred credits line linking to the project's page. The
    version shown is Info.plist's own CFBundleShortVersionString, already the VERSION file's
    contents (see setup.py) -- nothing to pass here for that. Activates the app first: without it,
    a panel asked for from the menu-bar item alone can open behind everything else."""
    AppKit.NSApp.activateIgnoringOtherApps_(True)
    paragraph = AppKit.NSMutableParagraphStyle.alloc().init()
    paragraph.setAlignment_(AppKit.NSTextAlignmentCenter)
    credits = AppKit.NSAttributedString.alloc().initWithString_attributes_(
        "kalkmancode.co.uk/beamer",
        {
            AppKit.NSLinkAttributeName: AppKit.NSURL.URLWithString_(BEAMER_SITE_URL),
            AppKit.NSParagraphStyleAttributeName: paragraph,
        },
    )
    AppKit.NSApp.orderFrontStandardAboutPanelWithOptions_({AppKit.NSAboutPanelOptionCredits: credits})


def install_main_menu(control_window):
    """rumps builds a status-bar menu and no main menu at all, and Beamer is not a status-bar-only
    app: it shows a real window with text fields in it. Cmd+Q is not built into AppKit — it is the
    key equivalent of the Quit item in the application menu — so with no main menu the app could
    not be quit from the keyboard, and Cmd+C/V/A in the token field did nothing either."""
    def item(menu, title, action, key, modifiers=None, target=None):
        entry = menu.addItemWithTitle_action_keyEquivalent_(title, action, key)
        if modifiers is not None:
            entry.setKeyEquivalentModifierMask_(modifiers)
        if target is not None:
            entry.setTarget_(target)
        return entry

    main_menu = AppKit.NSMenu.alloc().init()

    application_item = main_menu.addItemWithTitle_action_keyEquivalent_("Beamer", None, "")
    application_menu = AppKit.NSMenu.alloc().initWithTitle_("Beamer")
    item(application_menu, "About Beamer", "showAbout:", "", target=control_window)
    application_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    item(application_menu, "Hide Beamer", "hide:", "h")
    item(
        application_menu,
        "Hide Others",
        "hideOtherApplications:",
        "h",
        AppKit.NSEventModifierFlagCommand | AppKit.NSEventModifierFlagOption,
    )
    application_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    item(application_menu, "Quit Beamer", "quitApp:", "q", target=control_window)
    main_menu.setSubmenu_forItem_(application_menu, application_item)

    edit_item = main_menu.addItemWithTitle_action_keyEquivalent_("Edit", None, "")
    edit_menu = AppKit.NSMenu.alloc().initWithTitle_("Edit")
    item(edit_menu, "Undo", "undo:", "z")
    item(
        edit_menu,
        "Redo",
        "redo:",
        "z",
        AppKit.NSEventModifierFlagCommand | AppKit.NSEventModifierFlagShift,
    )
    edit_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    item(edit_menu, "Cut", "cut:", "x")
    item(edit_menu, "Copy", "copy:", "c")
    item(edit_menu, "Paste", "paste:", "v")
    item(edit_menu, "Select All", "selectAll:", "a")
    main_menu.setSubmenu_forItem_(edit_menu, edit_item)

    view_item = main_menu.addItemWithTitle_action_keyEquivalent_("View", None, "")
    view_menu = AppKit.NSMenu.alloc().initWithTitle_("View")
    for index, page in enumerate(pages.PAGES):
        item(view_menu, page[1], "showPage:", str(index + 1), target=control_window).setTag_(index)
    main_menu.setSubmenu_forItem_(view_menu, view_item)

    window_item = main_menu.addItemWithTitle_action_keyEquivalent_("Window", None, "")
    window_menu = AppKit.NSMenu.alloc().initWithTitle_("Window")
    # No target, so these travel the responder chain to whichever window is key rather than
    # being bound to one. Closing is safe to offer because the control window is created with
    # setReleasedWhenClosed_(False) and the menu-bar item reopens it.
    item(window_menu, "Close", "performClose:", "w")
    item(window_menu, "Minimise", "performMiniaturize:", "m")
    main_menu.setSubmenu_forItem_(window_menu, window_item)
    AppKit.NSApp.setWindowsMenu_(window_menu)

    AppKit.NSApp.setMainMenu_(main_menu)


class FlippedView(AppKit.NSView):
    """A plain view that lays out top-down, so the scrolling page starts at the top of the window
    rather than the bottom of the document."""

    def isFlipped(self):
        return True


class ControlWindow(AppKit.NSObject):
    def initWithController_settingsStore_logger_(self, controller, settings_store, logger):
        self = objc.super(ControlWindow, self).init()
        if self is None:
            return None
        self.controller = controller
        self.settings_store = settings_store
        self.logger = logger
        # Set by TrayApp once it exists: the listener for the PC's input, and
        # the second way an arrangement changed here can reach the PC.
        self.windows_input = None
        self.last_capture_attempt = 0.0
        # Set by TrayApp: the beacon listener whose PCs the Pair module lists.
        self.discovery = None
        self._pcs = []
        self._pcs_key = None
        self.chosen_pc = None
        self._pairing = False
        self._preview_flashes = 0
        self.latency = collections.deque(maxlen=widgets.Spark.SAMPLES)
        self.wide = None
        # Set by TrayApp: lights the chosen edge while the resistance ruler moves.
        self.preview = None
        self.has_notch = False
        # Set by TrayApp, for the Design page's Try it; the page builds its own preview loop.
        self.haptics = None
        self.previews = None
        self._apply_serial = 0
        self.page = None
        self.opened = False
        self.window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (900, 640)),
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
            | AppKit.NSWindowStyleMaskResizable,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("Beamer")
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self)
        self.window.setContentMinSize_(AppKit.NSMakeSize(*theme.MIN_WINDOW))
        # Vernier is dark only: the window pins to the palette rather than following the Mac's
        # appearance, and the transparent title bar takes the window's own ground.
        self.window.setAppearance_(AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua))
        self.window.setBackgroundColor_(theme.colour("ground"))
        self.window.setTitlebarAppearsTransparent_(True)
        self.window.center()
        content = self.window.contentView()
        content.setWantsLayer_(True)
        content.layer().setBackgroundColor_(theme.colour("ground").CGColor())

        top = widgets.hairline()
        self.sidebar = widgets.Sidebar(
            pages.PAGES,
            self._select_page,
            # Two lines: one, at the sidebar's narrowest, cuts the address off.
            footer_text=f"Beamer {VERSION}\nkalkmancode.co.uk/beamer",
            footer_label="Open kalkmancode.co.uk/beamer",
            on_footer=self._open_beamer_site,
        )
        divider = widgets.box("rule")
        pane = widgets.stack(spacing=0)
        for view in (top, self.sidebar.view, divider, pane):
            content.addSubview_(view)
        self.sidebar_width = self.sidebar.view.widthAnchor().constraintEqualToConstant_(theme.SIDEBAR_WIDTH[1])
        AppKit.NSLayoutConstraint.activateConstraints_([
            top.topAnchor().constraintEqualToAnchor_(content.topAnchor()),
            top.leadingAnchor().constraintEqualToAnchor_(content.leadingAnchor()),
            top.trailingAnchor().constraintEqualToAnchor_(content.trailingAnchor()),
            self.sidebar_width,
            self.sidebar.view.topAnchor().constraintEqualToAnchor_(top.bottomAnchor()),
            self.sidebar.view.bottomAnchor().constraintEqualToAnchor_(content.bottomAnchor()),
            self.sidebar.view.leadingAnchor().constraintEqualToAnchor_(content.leadingAnchor()),
            divider.widthAnchor().constraintEqualToConstant_(1),
            divider.topAnchor().constraintEqualToAnchor_(top.bottomAnchor()),
            divider.bottomAnchor().constraintEqualToAnchor_(content.bottomAnchor()),
            divider.leadingAnchor().constraintEqualToAnchor_(self.sidebar.view.trailingAnchor()),
            pane.topAnchor().constraintEqualToAnchor_(top.bottomAnchor()),
            pane.bottomAnchor().constraintEqualToAnchor_(content.bottomAnchor()),
            pane.leadingAnchor().constraintEqualToAnchor_(divider.trailingAnchor()),
            pane.trailingAnchor().constraintEqualToAnchor_(content.trailingAnchor()),
        ])
        # The page host is the only part of the pane that gives way when the window is resized;
        # the commit bar keeps its height on every page.
        host = widgets.box()
        host.setContentHuggingPriority_forOrientation_(
            AppKit.NSLayoutPriorityDefaultLow, AppKit.NSLayoutConstraintOrientationVertical
        )
        host.setContentCompressionResistancePriority_forOrientation_(
            AppKit.NSLayoutPriorityDefaultLow, AppKit.NSLayoutConstraintOrientationVertical
        )
        widgets.add(pane, host)
        widgets.add(pane, widgets.hairline())
        widgets.add(pane, self._commit())

        self.page_titles = []
        self.page_paddings = []
        self.pages = {}
        builders = {
            "overview": self._overview_page,
            "crossing": self._crossing_page,
            "design": self._design_page,
            "keyboard": self._keyboard_page,
            "pairing": self._pairing_page,
            "connection": self._connection_page,
            "permissions": self._permissions_page,
        }
        for key, name, _symbol, purpose in pages.PAGES:
            scroll, body = self._page(name, purpose)
            host.addSubview_(scroll)
            widgets.pin(scroll, host)
            scroll.setHidden_(True)
            self.pages[key] = scroll
            builders[key](body)

        self._load(config_to_raw(controller.cfg))
        self._select_page(pages.opening_page(None, accessibility_granted(), input_monitoring_granted()))
        self.windowDidResize_(None)
        self.refresh()
        return self

    def windowDidResize_(self, _notification):
        width = self.window.contentView().frame().size.width
        low, high = theme.SIDEBAR_WIDTH
        sidebar = min(high, max(low, width * 0.25))
        self.sidebar_width.setConstant_(sidebar)
        self._apply_width(width - sidebar - 1)

    @objc.python_method
    def _apply_width(self, width):
        """Two layouts, not a continuous reflow. Wide, the Overview's two controls sit side by
        side and Pairing puts the PC list beside the code; narrow, both stack and the large
        figures step down a size."""
        wide = width >= WIDE_WIDTH
        if wide == self.wide:
            return
        self.wide = wide
        narrow = not wide
        self.daily.arrange([[(0, 1), (1, 1)]] if wide else [[(0, 1)], [(1, 1)]], 2 if wide else 1)
        top, leading, bottom, trailing = theme.PAGE_PADDING_NARROW if narrow else theme.PAGE_PADDING
        for constraints in self.page_paddings:
            for constraint, constant in zip(constraints, (top, leading, bottom, trailing)):
                constraint.setConstant_(constant)
        for title in self.page_titles:
            title.set(size=theme.PAGE_TITLE_NARROW if narrow else theme.PAGE_TITLE)
        self.state_word.set(size=theme.TYPE["status_word_narrow" if narrow else "status_word"])
        for readout in (self.round_trip, self.resistance_readout, self.peer):
            readout.set_narrow(narrow)
        numeral = theme.TYPE["numeral_narrow" if narrow else "numeral"]
        self.resistance_numeral.set(size=numeral)
        self.double_tap_numeral.set(size=numeral)
        # Stacked, each half takes the full width; side by side, FillEqually shares it. The
        # distribution runs along the orientation, so stacked it must go back to Fill.
        self._show_peer()
        AppKit.NSLayoutConstraint.deactivateConstraints_(self.pair_stacked)
        self.pair_grid.setOrientation_(
            AppKit.NSUserInterfaceLayoutOrientationHorizontal if wide else AppKit.NSUserInterfaceLayoutOrientationVertical
        )
        self.pair_grid.setDistribution_(
            AppKit.NSStackViewDistributionFillEqually if wide else AppKit.NSStackViewDistributionFill
        )
        if narrow:
            AppKit.NSLayoutConstraint.activateConstraints_(self.pair_stacked)

    @objc.python_method
    def _select_page(self, key):
        self.page = key
        for name, scroll in self.pages.items():
            scroll.setHidden_(name != key)
        self.sidebar.select(key)
        if key != "keyboard":
            # Both recorders listen application-wide; left armed, they would take the first key
            # typed on another page.
            self.key_recorder.cancel()
            self.ignored_recorder.cancel()
        self._run_previews()

    @objc.python_method
    def _open_beamer_site(self):
        AppKit.NSWorkspace.sharedWorkspace().openURL_(AppKit.NSURL.URLWithString_(BEAMER_SITE_URL))

    @objc.python_method
    def _run_previews(self):
        """The previews play only while someone can see them: the Design page open in a visible
        window, with crossing animations switched on."""
        if self.previews is None:
            return
        if self.page == "design" and self.window.isVisible() and self.glow_box.value:
            self.previews.start()
        else:
            self.previews.stop()

    def showPage_(self, sender):
        self.opened = True
        self._select_page(pages.KEYS[sender.tag()])
        self.show()
    @objc.python_method
    def _load(self, raw):
        self.host_field.setStringValue_(str(raw["host"]))
        self.port_field.setStringValue_(str(raw["port"]))
        self.token_field.setStringValue_(str(raw["auth_token"]))
        self.token_plain.setStringValue_(str(raw["auth_token"]))
        self._say_pairing("Choose a PC, then type the code it shows.")
        self.key_recorder.set_value(raw["trigger_key"])
        self.ignored_entries = list(raw["ignored_inputs"])
        self._render_ignored()
        self.style_select.value = raw["trigger_style"]
        self.double_tap_ruler.value = raw["double_tap_ms"]
        self.double_tap_numeral.set(str(raw["double_tap_ms"]))
        self.modifier_select.value = raw["key_map"] if isinstance(raw["key_map"], str) else "custom"
        crossing_raw = raw["crossing"]
        for name, tile in self.method_boxes.items():
            tile.value = name in crossing_raw["methods"]
        self.edge_select.value = crossing_raw["edge"]
        self.corner_select.value = crossing_raw["corner"]
        self.resistance_ruler.value = crossing_raw["resistance_px"]
        self.haptics_box.value = crossing_raw["haptics"]
        self.glow_box.value = crossing_raw["glow"]
        self.dragging_box.value = crossing_raw["block_while_dragging"]
        self.notch_style_select.value = crossing_raw["notch_style"]
        self.notch_after_select.value = crossing_raw["notch_after_ms"]
        self.tick_feel_select.value = crossing_raw["haptic_feel"]
        self.tick_steps_select.value = crossing_raw["haptic_steps"]
        self.glow_style_select.value = crossing_raw["glow_style"]
        self.glow_colour_select.value = crossing_raw["glow_colour"]
        self._reflect()

    @objc.python_method
    def _reflect(self, *_ignored):
        """Enables each control only when the setting it edits is in play, and keeps the figures
        beside the rulers in step with them."""
        self.edge_select.set_enabled(self.method_boxes["edge"].value)
        self.corner_select.set_enabled(self.method_boxes["corner"].value)
        notch = self.method_boxes["notch"]
        notch.set_enabled(self.has_notch)
        haptics, glow = self.haptics_box.value, self.glow_box.value
        for control in (self.tick_feel_select, self.tick_steps_select, self.try_button):
            control.set_enabled(haptics)
        for control in (self.notch_style_select, self.notch_after_select, self.glow_style_select, self.glow_colour_select):
            control.set_enabled(glow)
        self.tick_note.set(
            {
                "quarters": "A tick at a quarter, half and three quarters of the push, then a firmer one as the pointer goes through.",
                "halves": "One tick halfway through the push, then a firmer one as the pointer goes through.",
                "breakthrough": "Nothing on the way in, then one firm tick as the pointer goes through.",
            }.get(self.tick_steps_select.value, "")
            if haptics
            else "Off: the trackpad stays still while you push."
        )
        after = (self.notch_after_select.value or 1200) / 1000
        self.notch_note.set(
            f"Once the pointer is through to Windows the notch keeps playing for {after:g} seconds, so the "
            "animation finishes instead of cutting off."
            + ("" if self.has_notch else " There is no notch at the top of the desktop right now, so nothing plays there.")
        )
        self._run_previews()
        notch_range = self.controller.notch_range
        notch.set_detail(
            f"Top edge, {round(notch_range[1] - notch_range[0])} pt wide" if self.has_notch and notch_range else "This Mac has no notch"
        )
        self.method_boxes["shortcut"].set_detail(widgets.key_title(self.key_recorder.value))
        self.ignored_recorder.set_trigger_code(KEY_NAME_TO_CODE.get(self.key_recorder.value))
        hold = self.style_select.value == "hold"
        self.double_tap_ruler.set_enabled(not hold)
        self.double_tap_head.setAlphaValue_(0.4 if hold else 1.0)
        self.style_hint.set(
            "Input is on Windows for as long as the key is held."
            if hold
            else "Tap twice to switch; tap twice again to come back."
        )
        resistance = self.resistance_ruler.value
        self.resistance_numeral.set(str(resistance))
        self.resistance_readout.value.set(str(resistance))
        self.resistance_scale.fraction = min(1.0, max(0.0, resistance / 500.0))
        self.resistance_scale.setNeedsDisplay_(True)
        self.resistance_hint.set(
            "Switches the moment the pointer touches the edge."
            if resistance == 0
            else f"How far to push past the edge before it gives. It applies as you drag, and lights the {self.edge_select.value} edge so you can see the size of it."
        )
        if self._preview_flashes == 0:
            self._place_preview(theme.PREVIEW_REST)
        self.modifier_note.set({
            "semantic": "Semantic: Command sends Control, Control sends the Windows key.",
            "positional": "Positional: Command sends the Windows key.",
        }.get(self.modifier_select.value, "Custom: the key map in config.json is kept as it is."))

    @objc.python_method
    def _preview_resistance(self, value):
        # Applied to the live engine at once, so the edge can be felt mid-drag; the saved setting
        # follows a moment later, once the ruler stops moving.
        self.controller.crossing.resistance_px = float(value)
        self._changed()
        if self.preview is not None and self.glow_box.value:
            self.preview(self.edge_select.value, min(1.0, value / 500.0))
        self._flash_preview(min(1.0, value / 500.0))

    @objc.python_method
    def _show_peer(self):
        cfg = self.controller.cfg
        self.peer.value.set(link_state.peer_name(cfg))
        if not cfg.host:
            self.peer_footer.set("Not paired")
        else:
            # The port does not fit a third of the status module at the narrow grid.
            self.peer_footer.set(f"{cfg.host}:{cfg.port}" if self.wide else cfg.host)

    @objc.python_method
    def _flash_preview(self, level):
        self._place_preview(0.3 + 0.7 * level)
        self._preview_flashes += 1
        flash = self._preview_flashes

        def fade():
            if flash != self._preview_flashes:
                return
            Quartz.CATransaction.begin()
            Quartz.CATransaction.setAnimationDuration_(0.6)
            self.preview_glow.setOpacity_(theme.PREVIEW_REST)
            Quartz.CATransaction.commit()

        AppHelper.callLater(0.5, fade)

    @objc.python_method
    def _place_preview(self, opacity):
        width, height = 44.0, 28.0
        frames = {
            "left": (((0, 0), (7, height)), (1, 0.5), (0, 0.5)),
            "right": (((width - 7, 0), (7, height)), (0, 0.5), (1, 0.5)),
            "top": (((0, height - 7), (width, 7)), (0.5, 0), (0.5, 1)),
            "bottom": (((0, 0), (width, 7)), (0.5, 1), (0.5, 0)),
        }
        frame, start, end = frames.get(self.edge_select.value, frames["right"])
        Quartz.CATransaction.begin()
        Quartz.CATransaction.setDisableActions_(True)
        self.preview_glow.setFrame_(frame)
        self.preview_glow.setStartPoint_(start)
        self.preview_glow.setEndPoint_(end)
        self.preview_glow.setOpacity_(opacity)
        Quartz.CATransaction.commit()

    @objc.python_method
    def _double_tap_moved(self, value):
        self.double_tap_numeral.set(str(value))
        self._changed()

    @objc.python_method
    def _changed(self, *_ignored):
        """Every control outside the Connection page calls this. The settings are written and
        applied once the control has been still for a moment, so a ruler being dragged writes once
        at the end rather than on every step."""
        self._reflect()
        self._apply_serial += 1
        serial = self._apply_serial
        AppHelper.callLater(0.3, lambda: serial == self._apply_serial and self._apply_settings())

    def windowWillClose_(self, _notification):
        self.key_recorder.cancel()
        self.ignored_recorder.cancel()
        if self.previews is not None:
            self.previews.stop()

    @objc.python_method
    def _head(self, title, figure):
        line = widgets.stack(vertical=False, spacing=12)
        line.setAlignment_(AppKit.NSLayoutAttributeTop)
        line.addArrangedSubview_(widgets.hug(widgets.eyebrow(title), AppKit.NSLayoutPriorityDefaultLow))
        line.addArrangedSubview_(figure)
        return line

    @objc.python_method
    def _numeral(self, unit):
        """A big mono figure and its unit. Returns (view, Figure)."""
        figure = widgets.Figure("0", theme.TYPE["numeral"], unit, tracking=theme.TIGHT["numeral"])
        return widgets.hug(figure.view), figure

    @objc.python_method
    def _page(self, title, purpose):
        """One page: a vertical scroller holding the title, the sentence saying what the page is
        for, then the modules the builder adds to the returned body. Returns (scroll, body)."""
        scroll = AppKit.NSScrollView.alloc().init()
        scroll.setTranslatesAutoresizingMaskIntoConstraints_(False)
        scroll.setDrawsBackground_(False)
        scroll.setHasVerticalScroller_(True)
        # Nothing scrolls sideways, at any width.
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        page = FlippedView.alloc().init()
        page.setTranslatesAutoresizingMaskIntoConstraints_(False)
        body = widgets.stack(spacing=theme.MODULE_GAP)
        page.addSubview_(body)
        top, leading, bottom, trailing = theme.PAGE_PADDING
        padding = [
            body.topAnchor().constraintEqualToAnchor_constant_(page.topAnchor(), top),
            body.leadingAnchor().constraintEqualToAnchor_constant_(page.leadingAnchor(), leading),
            page.bottomAnchor().constraintEqualToAnchor_constant_(body.bottomAnchor(), bottom),
            page.trailingAnchor().constraintEqualToAnchor_constant_(body.trailingAnchor(), trailing),
        ]
        AppKit.NSLayoutConstraint.activateConstraints_(padding)
        self.page_paddings.append(padding)
        scroll.setDocumentView_(page)
        clip = scroll.contentView()
        AppKit.NSLayoutConstraint.activateConstraints_([
            page.topAnchor().constraintEqualToAnchor_(clip.topAnchor()),
            page.leadingAnchor().constraintEqualToAnchor_(clip.leadingAnchor()),
            page.widthAnchor().constraintEqualToAnchor_(clip.widthAnchor()),
        ])
        header = widgets.stack(spacing=6)
        heading = widgets.Label(title, theme.PAGE_TITLE, 700, tracking=-0.01)
        self.page_titles.append(heading)
        widgets.add(header, heading.view)
        purpose_label = widgets.Label(purpose, theme.TYPE["body"], ink="ink_2", wrap=True)
        purpose_label.view.widthAnchor().constraintLessThanOrEqualToConstant_(theme.READING_WIDTH).setActive_(True)
        widgets.add(header, purpose_label.view)
        widgets.add(body, header)
        body.setCustomSpacing_afterView_(32, header)
        return scroll, body

    @objc.python_method
    def _overview_page(self, body):
        widgets.add(body, self._status_module().view)
        self.daily = widgets.Rack(
            [self._keyboard_module(), self._pause_module()], bottom_rule=False, gap=theme.MODULE_GAP, fill=None
        )
        widgets.add(body, self.daily.view)
        widgets.add(body, self._login_module().view)

    @objc.python_method
    def _login_module(self):
        module = widgets.Module(spacing=10)
        self.login_switch = widgets.Switch("Start Beamer when you log in", on_change=self._set_login)
        module.add(self.login_switch.view)
        self.login_note = widgets.note()
        module.add(self.login_note.view)
        self._show_login_state()
        return module

    @objc.python_method
    def _show_login_state(self, refused=None):
        try:
            state = login_item.status()
        except Exception:
            self.logger.exception("could not read the login item")
            state = login_item.NOT_FOUND
        self.login_switch.value = state in (login_item.ENABLED, login_item.REQUIRES_APPROVAL)
        if refused:
            self.login_note.set(f"macOS refused: {refused}")
        elif state == login_item.REQUIRES_APPROVAL:
            self.login_note.set("Waiting for you to allow it in System Settings, General, Login Items.")
        else:
            self.login_note.set("In the menu bar, with no window.")

    @objc.python_method
    def _set_login(self, enabled):
        try:
            login_item.set_enabled(enabled)
        except OSError as exc:
            self.logger.warning("could not change the login item: %s", exc)
            self._show_login_state(refused=exc)
            return
        self._show_login_state()

    @objc.python_method
    def _crossing_page(self, body):
        for module in (self._ways_module(), self._resistance_module()):
            widgets.add(body, module.view)

    @objc.python_method
    def _design_page(self, body):
        self.previews = previews.PreviewLoop(self.controller)
        for module in (self._on_screen_module(), self._notch_module(), self._edge_module(), self._trackpad_module()):
            widgets.add(body, module.view)

    @objc.python_method
    def _keyboard_page(self, body):
        widgets.add(body, self._shortcut_module().view)
        widgets.add(body, self._ignored_module().view)
        widgets.add(body, self._modifier_module().view)

    @objc.python_method
    def _pairing_page(self, body):
        widgets.add(body, self._paired_module().view)
        widgets.add(body, self._pair_module().view)

    @objc.python_method
    def _connection_page(self, body):
        widgets.add(body, self._connection_module().view)

    @objc.python_method
    def _permissions_page(self, body):
        widgets.add(body, self._access_module().view)

    @objc.python_method
    def _status_module(self):
        module = widgets.Module(spacing=10)
        head = widgets.stack(vertical=False, spacing=7)
        head.addArrangedSubview_(widgets.hug(widgets.eyebrow("Link"), AppKit.NSLayoutPriorityDefaultLow))
        self.link_led = widgets.LED()
        head.addArrangedSubview_(self.link_led.view)
        self.link_tag = widgets.Label("", theme.TYPE["eyebrow"], 700, "ink_3", tracking=theme.TRACKING["eyebrow"], upper=True)
        head.addArrangedSubview_(self.link_tag.view)
        module.add(head)
        self.state_word = widgets.Label("", theme.TYPE["status_word"], 700, tracking=theme.TIGHT["status_word"])
        widgets.squeeze(self.state_word.view)
        module.add(self.state_word.view)
        self.state_detail = widgets.Label("", theme.TYPE["body"], ink="ink_2", wrap=True)
        # Two lines reserved, so a one-line state does not pull the readouts up and down.
        self.state_detail.view.heightAnchor().constraintGreaterThanOrEqualToConstant_(36).setActive_(True)
        module.add(self.state_detail.view)
        self.spark = widgets.size(widgets.flipped(widgets.Spark), height=14)
        self.round_trip = widgets.Readout("Round trip", "ms", self.spark)
        self.resistance_scale = widgets.size(widgets.flipped(widgets.Scale), height=14)
        self.resistance_readout = widgets.Readout("Resistance", "px", self.resistance_scale)
        self.peer_footer = widgets.Label("", theme.TYPE["small"], mono=True, ink="ink_3")
        widgets.squeeze(self.peer_footer.view)
        self.peer = widgets.Readout("Peer", "", self.peer_footer.view, sizes=(theme.PEER_SIZE, theme.PEER_SIZE_NARROW))
        module.add(widgets.grid([self.round_trip.view, self.resistance_readout.view, self.peer.view], 3))
        return module

    @objc.python_method
    def _keyboard_module(self):
        module = widgets.Module(spacing=14)
        module.add(widgets.eyebrow("Keyboard and pointer"))
        self.selector = widgets.Selector()
        module.add(self.selector.view)
        self.toggle_button = widgets.Button(
            "Send input to Windows", self, "toggleRedirect:", style="primary", scale="big", full_width=True
        )
        module.add(self.toggle_button.view)
        return module

    @objc.python_method
    def _pause_module(self):
        module = widgets.Module(spacing=14)
        module.add(widgets.eyebrow("Pointer crossing"))
        self.pause_button = widgets.Button("Pause crossing", self, "togglePause:", full_width=True)
        module.add(self.pause_button.view)
        self.crossing_state = widgets.note()
        module.add(self.crossing_state.view)
        return module

    @objc.python_method
    def _resistance_module(self):
        module = widgets.Module()
        figure, self.resistance_numeral = self._numeral("px of push")
        module.add(self._head("Resistance", figure))
        self.resistance_ruler = widgets.Ruler(
            0, 500, (0, 100, 200, 300, 400, 500), step=1, minor=25, on_change=self._preview_resistance
        )
        module.add(self.resistance_ruler.view)
        line = widgets.stack(vertical=False, spacing=10)
        line.setAlignment_(AppKit.NSLayoutAttributeTop)
        screen = widgets.size(widgets.box("ground", "edge", 3), 46, 30)
        screen.layer().setMasksToBounds_(True)
        self.preview_glow = Quartz.CAGradientLayer.layer()
        self.preview_glow.setColors_([
            theme.colour("signal").colorWithAlphaComponent_(0).CGColor(), theme.colour("signal").CGColor(),
        ])
        screen.layer().addSublayer_(self.preview_glow)
        line.addArrangedSubview_(screen)
        self.resistance_hint = widgets.note()
        line.addArrangedSubview_(self.resistance_hint.view)
        module.add(line)
        return module

    @objc.python_method
    def _ways_module(self):
        module = widgets.Module()
        module.add(widgets.eyebrow("Ways in"))
        self.ways_note = widgets.note()
        module.add(self.ways_note.view)
        self.method_boxes = {
            "shortcut": widgets.WayTile("Shortcut", on_change=self._changed),
            "edge": widgets.WayTile("Edge", "One whole outer edge", on_change=self._changed),
            "corner": widgets.WayTile("Corner", f"{crossing.CORNER_PX:g} pt box, diagonal push", on_change=self._changed),
            "notch": widgets.WayTile("Notch", on_change=self._changed),
        }
        module.add(widgets.grid([tile.view for tile in self.method_boxes.values()], 2))
        self.edge_select = widgets.Segmented(
            [("left", "Left"), ("right", "Right"), ("top", "Top"), ("bottom", "Bottom")], on_change=self._changed
        )
        module.add(widgets.field_row("Edge", self.edge_select.view)[0])
        self.corner_select = widgets.Segmented(
            [
                ("top_left", "Top left"),
                ("top_right", "Top right"),
                ("bottom_left", "Bottom left"),
                ("bottom_right", "Bottom right"),
            ],
            columns=2,
            on_change=self._changed,
        )
        module.add(widgets.field_row("Corner", self.corner_select.view)[0])
        self.dragging_box = widgets.Switch("Never while dragging", on_change=self._changed)
        module.add(self.dragging_box.view)
        return module

    @objc.python_method
    def _shortcut_module(self):
        module = widgets.Module()
        self.double_tap_head, self.double_tap_numeral = self._numeral("ms between taps")
        module.add(self._head("Shortcut", self.double_tap_head))
        self.key_recorder = widgets.KeyRecorder("alt_r", on_change=self._changed)
        module.add(self.key_recorder.view)
        self.style_select = widgets.Segmented([("double_tap", "Double-tap"), ("hold", "Hold")], on_change=self._changed)
        module.add(widgets.field_row("Trigger style", self.style_select.view)[0])
        # The stored window runs 50 to 2000 ms, but only about 150 to 600 is useful, so the ruler
        # shows 50 to 1000 on a square-root scale; a stored value past 1000 pins the thumb.
        self.double_tap_ruler = widgets.Ruler(
            50, 1000, (50, 150, 300, 600, 1000), step=10, scale="sqrt", minor=20, on_change=self._double_tap_moved
        )
        module.add(self.double_tap_ruler.view)
        self.style_hint = widgets.note()
        module.add(self.style_hint.view)
        return module

    @objc.python_method
    def _ignored_module(self):
        module = widgets.Module()
        module.add(widgets.eyebrow("Stays on this Mac"))
        module.add(widgets.note(
            "These keys and buttons keep working on this Mac while its input is on Windows: a "
            "mouse's back button for this Mac's browser, say, or a volume key for its speakers."
        ).view)
        self.ignored_entries = []
        self.ignored_list = widgets.stack(spacing=6)
        module.add(self.ignored_list)
        self.ignored_empty = widgets.note("Nothing yet. Every key and button goes to Windows while it has input.")
        module.add(self.ignored_empty.view)
        self.ignored_recorder = widgets.IgnoredRecorder(
            KEY_NAME_TO_CODE.get(self.key_recorder.value), on_recorded=self._add_ignored
        )
        module.add(self.ignored_recorder.view)
        self.ignored_status = widgets.note()
        module.add(self.ignored_status.view)
        self._render_ignored()
        return module

    @objc.python_method
    def _render_ignored(self):
        for view in list(self.ignored_list.arrangedSubviews()):
            self.ignored_list.removeArrangedSubview_(view)
            view.removeFromSuperview()
        for entry in self.ignored_entries:
            # One quiet row per entry, as on Windows: the name, and a small Remove that does not
            # outweigh it.
            title = ignored_titles.entry_title(entry)
            chip = widgets.box("well", "rule", theme.RADIUS["field"])
            name = widgets.Label(title, theme.TYPE["small"], 600, mono=True)
            remove = widgets.pressable(lambda entry=entry: self._remove_ignored(entry), radius=theme.RADIUS["field"])
            remove.setAccessibilityLabel_(f"Remove {title}")
            remove_word = widgets.Label("Remove", theme.TYPE["small"], ink="ink_3")
            remove.addSubview_(remove_word.view)
            widgets.pin(remove_word.view, remove, (4, 8, 4, 8))
            line = widgets.stack(vertical=False, spacing=10)
            line.addArrangedSubview_(name.view)
            line.addArrangedSubview_(remove)
            widgets.hug(name.view, AppKit.NSLayoutPriorityDefaultLow)
            chip.addSubview_(line)
            widgets.pin(line, chip, (5, 12, 5, 4))
            widgets.add(self.ignored_list, chip)
        self.ignored_empty.view.setHidden_(bool(self.ignored_entries))

    @objc.python_method
    def _add_ignored(self, entry):
        if entry is None:
            self.ignored_status.set("That key is the shortcut; it always stays with Beamer.")
            return
        if entry in self.ignored_entries:
            return
        self.ignored_entries.append(entry)
        self.ignored_status.set("")
        self._render_ignored()
        self._changed()

    @objc.python_method
    def _remove_ignored(self, entry):
        self.ignored_entries.remove(entry)
        self.ignored_status.set("")
        self._render_ignored()
        self._changed()

    @objc.python_method
    def _on_screen_module(self):
        module = widgets.Module(spacing=8)
        module.add(widgets.eyebrow("On screen"))
        self.glow_box = widgets.Switch("Animate crossings on this Mac", on_change=self._changed)
        module.add(self.glow_box.view)
        module.add(widgets.note(
            "Lights the notch or the edge as you push toward Windows. Switched off, crossing still "
            "works; you feel it rather than see it. Windows sets how its own edge looks."
        ).view)
        return module

    @objc.python_method
    def _preview_tile(self, base, value, title, detail, notch, **overrides):
        """One tile's preview: its own screen, a feed pinned to the style the tile shows, and the
        real renderer hosted on it, registered with the page's loop."""
        screen = widgets.size(previews.PreviewScreen.alloc().init().setup(notch), height=84)
        feed = previews.PreviewFeed(self.controller, **overrides)
        if notch is None:
            renderer = previews.hosted_edge(base)(feed, self.logger, screen)
            update = previews.edge_update(renderer)
        else:
            renderer = previews.hosted_notch(base)(feed, self.logger, screen)
            update = previews.notch_update(renderer)
        self.previews.add(feed, renderer, update)
        return value, title, detail, screen

    @objc.python_method
    def _notch_module(self):
        module = widgets.Module()
        module.add(widgets.eyebrow("Notch"))
        notch = previews.notch_size()
        self.notch_style_select = widgets.ChoiceTiles(
            [
                self._preview_tile(NotchBeam, "beam", "Beam", "A line of colour runs round the notch, faster the harder you push.", notch),
                self._preview_tile(NotchIsland, "island", "Island", "The notch grows as you push, with a meter inside, and flashes as you go through.", notch),
            ],
            on_change=self._changed,
        )
        module.add(self.notch_style_select.view)
        self.notch_after_select = widgets.Segmented(
            [(600, "0.6 s"), (1200, "1.2 s"), (2000, "2 s"), (3000, "3 s")], on_change=self._changed
        )
        module.add(widgets.field_row("Keep animating", self.notch_after_select.view)[0])
        self.notch_note = widgets.note()
        module.add(self.notch_note.view)
        return module

    @objc.python_method
    def _edge_module(self):
        module = widgets.Module()
        module.add(widgets.eyebrow("Edge and corner"))
        self.glow_style_select = widgets.ChoiceTiles(
            [
                self._preview_tile(EdgeGlow, "glow", "Glow", "A band of light that deepens the harder you push.", None, glow_style="glow"),
                self._preview_tile(EdgeGlow, "beam", "Beam", "A thin line with a comet of light running along it.", None, glow_style="beam"),
            ],
            on_change=self._changed,
        )
        module.add(self.glow_style_select.view)
        self.glow_colour_select = widgets.Swatches(
            [(name, name.capitalize()) for name in crossing.GLOW_COLOURS], on_change=self._changed
        )
        module.add(widgets.field_row("Colour", self.glow_colour_select.view)[0])
        module.add(widgets.note("The notch's Beam style uses this colour too. Island keeps Beamer's own cyan.").view)
        return module

    @objc.python_method
    def _trackpad_module(self):
        module = widgets.Module()
        module.add(widgets.eyebrow("Trackpad"))
        self.haptics_box = widgets.Switch("Tick as the push builds", on_change=self._changed)
        module.add(self.haptics_box.view)
        strength = widgets.stack(vertical=False, spacing=10)
        self.tick_feel_select = widgets.Segmented(
            [("light", "Light"), ("medium", "Medium"), ("firm", "Firm")], on_change=self._changed
        )
        strength.addArrangedSubview_(widgets.hug(self.tick_feel_select.view, AppKit.NSLayoutPriorityDefaultLow))
        self.try_button = widgets.Button("Try it", self, "tryTick:", scale="small")
        strength.addArrangedSubview_(self.try_button.view)
        module.add(widgets.field_row("Strength", strength)[0])
        self.tick_steps_select = widgets.Segmented(
            [("quarters", "Every quarter"), ("halves", "Halfway"), ("breakthrough", "Only when through")],
            on_change=self._changed,
        )
        module.add(widgets.field_row("Ticks at", self.tick_steps_select.view)[0])
        self.tick_note = widgets.note()
        module.add(self.tick_note.view)
        return module

    def tryTick_(self, _sender):
        if self.haptics is not None:
            self.haptics.tick(self.tick_feel_select.value)

    @objc.python_method
    def _modifier_module(self):
        module = widgets.Module()
        module.add(widgets.eyebrow("Modifier keys"))
        self.modifier_select = widgets.Segmented(
            [("semantic", "Semantic"), ("positional", "Positional")], on_change=self._changed
        )
        module.add(self.modifier_select.view)
        self.modifier_note = widgets.note()
        module.add(self.modifier_note.view)
        return module

    @objc.python_method
    def _paired_module(self):
        """What the page leads with once a PC is paired: which one, where, and the one way to change
        it. The PC list and code boxes stay hidden until they are wanted, or they read as an
        invitation to pair a Mac that already is."""
        module = widgets.Module()
        module.add(widgets.eyebrow("Paired with"))
        self.paired_name = widgets.Label("", theme.TYPE["readout"], 400, mono=True)
        module.add(self.paired_name.view)
        self.paired_address = widgets.Label("", theme.TYPE["small"], mono=True, ink="ink_3")
        module.add(self.paired_address.view)
        line = widgets.stack(vertical=False, spacing=10)
        line.setAlignment_(AppKit.NSLayoutAttributeCenterY)
        self.paired_note = widgets.note()
        line.addArrangedSubview_(self.paired_note.view)
        self.repair_button = widgets.Button("Pair a different PC", self, "togglePairing:", scale="small")
        line.addArrangedSubview_(self.repair_button.view)
        module.add(line)
        self.paired_module = module
        return module

    @objc.python_method
    def _pair_module(self):
        module = widgets.Module()
        self.pair_grid = widgets.stack(spacing=20)
        self.pair_grid.setAlignment_(AppKit.NSLayoutAttributeTop)
        found = widgets.stack(spacing=8)
        widgets.add(found, widgets.eyebrow("On this network"))
        self.pc_list = widgets.stack(spacing=1)
        self.pc_frame = widgets.box("rule")
        self.pc_frame.addSubview_(self.pc_list)
        widgets.pin(self.pc_list, self.pc_frame, (1, 1, 1, 1))
        widgets.add(found, self.pc_frame)
        self.pc_empty = widgets.note()
        widgets.add(found, self.pc_empty.view)
        code = widgets.stack(spacing=8)
        widgets.add(code, widgets.eyebrow("Code shown on the PC"))
        self.code_boxes = widgets.CodeBoxes(pairing.CODE_DIGITS, self.confirmPair_)
        widgets.add(code, self.code_boxes.view)
        line = widgets.stack(vertical=False, spacing=10)
        line.setAlignment_(AppKit.NSLayoutAttributeTop)
        self.pair_status = widgets.note()
        line.addArrangedSubview_(self.pair_status.view)
        self.confirm_button = widgets.Button("Pair", self, "confirmPair:", scale="small")
        line.addArrangedSubview_(self.confirm_button.view)
        widgets.add(code, line)
        self.pair_grid.addArrangedSubview_(found)
        self.pair_grid.addArrangedSubview_(code)
        module.add(self.pair_grid)
        self.pair_stacked = [
            view.widthAnchor().constraintEqualToAnchor_(self.pair_grid.widthAnchor()) for view in (found, code)
        ]
        self.pair_module = module
        return module

    @objc.python_method
    def _connection_module(self):
        module = widgets.Module(spacing=10)
        host_box, self.host_field = widgets.field()
        module.add(widgets.field_row("Windows address", host_box)[0])
        port_box, self.port_field = widgets.field()
        module.add(widgets.field_row("Port", port_box)[0])
        token_box, self.token_field = widgets.field(secure=True)
        plain_box, self.token_plain = widgets.field()
        plain_box.setHidden_(True)
        self.token_boxes = (token_box, plain_box)
        self.show_button = widgets.Button("Show", self, "showToken:", scale="small")
        token_line = widgets.stack(vertical=False, spacing=6)
        token_line.addArrangedSubview_(token_box)
        token_line.addArrangedSubview_(plain_box)
        token_line.addArrangedSubview_(self.show_button.view)
        for box in self.token_boxes:
            widgets.hug(box, AppKit.NSLayoutPriorityDefaultLow)
        module.add(widgets.field_row("Shared token", token_line)[0])
        self.wake_state = widgets.Label("", theme.TYPE["small"], mono=True)
        module.add(widgets.field_row("Wake-on-LAN", self.wake_state.view)[0])
        self.wake_hint = widgets.note()
        module.add(self.wake_hint.view)
        module.add(widgets.hairline())
        line = widgets.stack(vertical=False, spacing=12)
        line.addArrangedSubview_(widgets.note("A new address, port or token takes effect when you connect.").view)
        line.addArrangedSubview_(widgets.Button("Connect", self, "connect:", style="primary", scale="small").view)
        module.add(line)
        return module

    @objc.python_method
    def _access_module(self):
        module = widgets.Module(spacing=10)
        self.access_status, self.access_button = self._permission_row(module, "Accessibility", "requestAccessibility:")
        module.add(widgets.hairline())
        self.input_status, self.input_button = self._permission_row(module, "Input Monitoring", "requestInputMonitoring:")
        self.capture_status = widgets.note()
        module.add(self.capture_status.view)
        return module

    @objc.python_method
    def _permission_row(self, module, name, action):
        line = widgets.stack(vertical=False, spacing=10)
        words = widgets.stack(spacing=4)
        widgets.add(words, widgets.Label(name, theme.TYPE["body"], 600).view)
        status = widgets.Label("Required", theme.TYPE["small"], mono=True, ink="amber", tracking=theme.STATE_TRACKING, upper=True)
        widgets.add(words, status.view)
        line.addArrangedSubview_(widgets.hug(words, AppKit.NSLayoutPriorityDefaultLow))
        button = widgets.Button("Grant", self, action, scale="small")
        line.addArrangedSubview_(button.view)
        module.add(line)
        return status, button

    @objc.python_method
    def _ways_in_sentence(self):
        cfg = self.controller.cfg
        key = widgets.key_title(cfg.trigger_key)
        methods = set(cfg.crossing["methods"])
        parts = []
        if "shortcut" in methods:
            parts.append(f"{'Hold' if cfg.trigger_style == 'hold' else 'Double-tap'} {key}")
        ways = []
        if "edge" in methods:
            ways.append(f"the {cfg.crossing['edge']} edge")
        if "corner" in methods:
            ways.append(f"the {cfg.crossing['corner'].replace('_', ' ')} corner")
        if "notch" in methods:
            ways.append("the notch")
        if ways:
            joined = ways[0] if len(ways) == 1 else ", ".join(ways[:-1]) + " or " + ways[-1]
            parts.append(f"push through {joined}")
        if not parts:
            return ""
        sentence = ", or ".join(parts)
        return sentence[0].upper() + sentence[1:]

    @objc.python_method
    def _commit(self):
        bar = widgets.box("ground")
        self.message_label = widgets.note(
            "Changes apply as you make them. Closing this window keeps Beamer running in the menu bar."
        )
        line = widgets.stack(vertical=False, spacing=16)
        line.addArrangedSubview_(self.message_label.view)
        bar.addSubview_(line)
        widgets.pin(line, bar, (12, 16, 12, 16))
        return bar

    @objc.python_method
    def _say(self, message, ink="ink_2"):
        self.message_label.set(message, ink=ink)

    @objc.python_method
    def show(self):
        self._select_page(pages.opening_page(
            self.page if self.opened else None, accessibility_granted(), input_monitoring_granted()
        ))
        self.opened = True
        self.window.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        self._run_previews()

    @objc.python_method
    def _token(self):
        return (self.token_plain if self.token_boxes[0].isHidden() else self.token_field).stringValue()

    def showToken_(self, _sender):
        secure_box, plain_box = self.token_boxes
        showing = plain_box.isHidden()
        if showing:
            self.token_plain.setStringValue_(self.token_field.stringValue())
        else:
            self.token_field.setStringValue_(self.token_plain.stringValue())
        secure_box.setHidden_(showing)
        plain_box.setHidden_(not showing)
        self.show_button.set_title("Hide" if showing else "Show")

    def connect_(self, _sender):
        """The Connection page's own commit: a new address, port or token has to reconnect, so it
        waits for the button rather than applying as it is typed."""
        raw = config_to_raw(self.controller.cfg)
        try:
            raw["host"] = self.host_field.stringValue().strip()
            raw["port"] = int(self.port_field.stringValue().strip())
            raw["auth_token"] = self._token()
            if raw["host"] != self.controller.cfg.host:
                # What was learned belonged to the old address.
                raw["pc_name"] = ""
                raw["mac_address"] = ""
            cfg = self.settings_store.save(raw)
        except (SettingsError, TypeError, ValueError) as exc:
            self._say(str(exc), "fault")
            return
        self._say("Saved. Connecting…", "signal")
        self.controller.update_config(cfg)

    @objc.python_method
    def _apply_settings(self):
        """Writes every setting outside the Connection page and applies it without dropping the link."""
        raw = config_to_raw(self.controller.cfg)
        try:
            raw["trigger_key"] = self.key_recorder.value
            raw["ignored_inputs"] = list(self.ignored_entries)
            raw["trigger_style"] = self.style_select.value
            raw["double_tap_ms"] = self.double_tap_ruler.value
            if self.modifier_select.value in config_module.KEY_MAP_STYLES:
                raw["key_map"] = self.modifier_select.value
            raw["crossing"] = {
                "methods": [name for name, tile in self.method_boxes.items() if tile.value],
                "edge": self.edge_select.value,
                "corner": self.corner_select.value,
                "resistance_px": self.resistance_ruler.value,
                "haptics": self.haptics_box.value,
                "glow": self.glow_box.value,
                "notch_style": self.notch_style_select.value,
                "notch_after_ms": self.notch_after_select.value,
                "haptic_feel": self.tick_feel_select.value,
                "haptic_steps": self.tick_steps_select.value,
                "glow_style": self.glow_style_select.value,
                "glow_colour": self.glow_colour_select.value,
                "block_while_dragging": self.dragging_box.value,
                "arrangement_set_at": self.controller.cfg.crossing.get("arrangement_set_at", 0),
            }
            moved = raw["crossing"]["edge"] != self.controller.cfg.crossing.get("edge")
            if moved:
                # The edge is half of a value Windows holds too, so a change
                # here is stamped with the moment it was made. When the two
                # ends meet holding different answers -- one changed while the
                # other was asleep -- the newer stamp is the one that stands.
                raw["crossing"]["arrangement_set_at"] = int(time.time())
            cfg = self.settings_store.save(raw)
        except (SettingsError, TypeError, ValueError) as exc:
            self._say(str(exc), "fault")
            return
        # apply_settings sends it over this Mac's own link; the PC's link is
        # the other way it can be reached, and either may be the one that is
        # up. Both are best-effort and say so by returning False.
        self.controller.apply_settings(cfg)
        if moved and self.windows_input is not None:
            self.windows_input.send_arrangement(
                cfg.crossing["edge"], cfg.crossing.get("arrangement_set_at", 0)
            )
        self._say("Saved. Changes apply as you make them.", "ink_2")

    @objc.python_method
    def apply_arrangement(self, mac_edge, set_at):
        """Windows changed which edge of this Mac leads to it. Applied here
        rather than at either link, because this is the side that owns the
        settings file. An arrangement older than this Mac's own is ignored:
        both ends stamp their changes, and the newer one stands."""
        if mac_edge == self.controller.cfg.crossing.get("edge"):
            return
        mine = self.controller.cfg.crossing.get("arrangement_set_at", 0)
        if mine and not protocol.arrangement_wins(set_at, mine):
            self.logger.info("ignoring an older arrangement from the PC (%s vs %s)", set_at, mine)
            return
        raw = config_to_raw(self.controller.cfg)
        raw["crossing"] = {**raw["crossing"], "edge": mac_edge, "arrangement_set_at": int(set_at)}
        try:
            cfg = self.settings_store.save(raw)
        except (SettingsError, TypeError, ValueError):
            self.logger.exception("could not save the arrangement the PC sent")
            return
        self.controller.cfg = cfg
        self.controller.crossing = crossing.CrossingEngine.from_config(cfg.crossing)
        self.logger.info("the PC moved the crossing to this Mac's %s edge", mac_edge)
        self.refresh()

    def quitApp_(self, _sender):
        self.quit_handler()

    def showAbout_(self, _sender):
        show_about_panel()

    def requestAccessibility_(self, _sender):
        ApplicationServices.AXIsProcessTrustedWithOptions(
            {ApplicationServices.kAXTrustedCheckOptionPrompt: True}
        )
        self.refresh()

    def requestInputMonitoring_(self, _sender):
        Quartz.CGRequestListenEventAccess()
        self.refresh()

    def toggleRedirect_(self, _sender):
        if not self.controller.input_ready:
            self._say("Grant both Mac permissions first.", "fault")
            return
        if not self.controller.redirecting and self.controller.can_wake:
            self.controller.wake()
            self._say("Waking Windows. It connects on its own once it is up.", "ink_2")
        elif not self.controller.set_redirecting(not self.controller.redirecting):
            self._say(self.controller.connection_status, "fault")
        self.refresh()

    def togglePause_(self, _sender):
        self.controller.crossing_paused = not self.controller.crossing_paused
        self.refresh()

    def togglePairing_(self, _sender):
        self._repairing = not getattr(self, "_repairing", False)
        if not self._repairing:
            self.code_boxes.clear()
            self.chosen_pc = None
            self._pcs_key = None
        self._say_pairing("Choose a PC, then type the code it shows.")
        self.refresh()

    @objc.python_method
    def _refresh_paired(self, state):
        cfg = self.controller.cfg
        paired = bool(cfg.auth_token)
        refused = state.key == "token"
        repairing = getattr(self, "_repairing", False)
        peer = link_state.peer_name(cfg)
        self.paired_module.view.setHidden_(not paired)
        self.pair_module.view.setHidden_(paired and not refused and not repairing)
        self.paired_name.set(peer)
        self.paired_address.set(f"{cfg.host}  ·  port {cfg.port}")
        if refused:
            self.paired_note.set(f"{peer} refused this Mac's token. Pair again below with the code it shows.", ink="fault")
        elif state.key in ("mac", "windows", "paused", "full_screen", "unlocking"):
            self.paired_note.set("Connected now.", ink="signal")
        else:
            self.paired_note.set("Beamer connects to it on its own whenever both are running.", ink="ink_2")
        self.repair_button.set_title("Cancel" if repairing else "Pair a different PC")
        self.repair_button.view.setHidden_(refused)

    @objc.python_method
    def _say_pairing(self, message, ink="ink_2"):
        self.pair_status.set(message, ink=ink)

    @objc.python_method
    def _refresh_pcs(self):
        """Rebuilds the PC rows only when what they would show has changed; the timer that
        drives this ticks several times a second."""
        discovery = self.discovery
        pcs = discovery.pcs() if discovery is not None else []
        chosen = self.chosen_pc["address"] if self.chosen_pc is not None else None
        key = (chosen, tuple((pc["name"], pc["address"], pc["port"], pc["pair_id"] is not None) for pc in pcs))
        if key == self._pcs_key:
            return
        self._pcs_key = key
        self._pcs = pcs
        for view in list(self.pc_list.arrangedSubviews()):
            self.pc_list.removeArrangedSubview_(view)
            view.removeFromSuperview()
        for index, pc in enumerate(pcs):
            picked = pc["address"] == chosen
            row = widgets.pressable(lambda index=index: self._choose_pc(index), "well" if picked else "ground",
                                    role=AppKit.NSAccessibilityRadioButtonRole)
            row.ring_inset = 1.0
            showing = pc["pair_id"] is not None
            row.setAccessibilityLabel_(f"{pc['name']}, {pc['address']}" + (", showing a code" if showing else ""))
            row.setToolTip_(f"Port {pc['port']}" + (", showing a code" if showing else ""))
            line = widgets.stack(vertical=False, spacing=9)
            led = widgets.LED()
            led.set("signal" if showing else "off")
            line.addArrangedSubview_(led.view)
            name = widgets.Label(pc["name"], theme.TYPE["note"], 600 if picked else 400)
            line.addArrangedSubview_(widgets.hug(widgets.squeeze(name.view), AppKit.NSLayoutPriorityDefaultLow))
            line.addArrangedSubview_(widgets.Label(pc["address"], theme.TYPE["small"], mono=True, ink="ink_3").view)
            row.addSubview_(line)
            widgets.pin(line, row, (7, 10, 7, 10))
            widgets.add(self.pc_list, row)
        if discovery is not None and discovery.error:
            self.pc_empty.set(f"Beamer cannot look for PCs: {discovery.error}", ink="fault")
        else:
            self.pc_empty.set(
                "Looking for PCs running Beamer on this network. Open Beamer on the PC and it appears here.", ink="ink_2"
            )
        self.pc_frame.setHidden_(not pcs)
        self.pc_empty.view.setHidden_(bool(pcs))
        if chosen is not None and chosen not in {pc["address"] for pc in pcs}:
            self.chosen_pc = None
            self._pcs_key = None
        self.confirm_button.set_enabled(self.chosen_pc is not None and not self._pairing)

    @objc.python_method
    def _choose_pc(self, index):
        if not 0 <= index < len(self._pcs):
            return
        self.chosen_pc = self._pcs[index]
        self.code_boxes.clear()
        self.code_boxes.view.setAccessibilityLabel_(f"Code shown on {self.chosen_pc['name']}")
        if self.chosen_pc["pair_id"] is None:
            self._say_pairing(f"{self.chosen_pc['name']} is not showing a code yet. Press Pair a Mac on it first.")
        else:
            self._say_pairing("Six digits, as shown on the PC.")
        self._refresh_pcs()
        self.code_boxes.focus(self.window)

    def confirmPair_(self, _sender):
        pc = self.chosen_pc
        if pc is None or self._pairing or self.discovery is None:
            return
        code = re.sub(r"\D", "", self.code_boxes.value)
        if len(code) != pairing.CODE_DIGITS:
            self._say_pairing(f"The code is {pairing.CODE_DIGITS} digits.", "fault")
            return
        # The list may have refreshed since the row was chosen; pair with the PC's latest beacon.
        current = next((entry for entry in self._pcs if entry["address"] == pc["address"]), pc)
        if current["pair_id"] is None:
            self._say_pairing(f"{current['name']} is not showing a code. Press Pair a Mac on it, then try again.", "fault")
            return
        self._pairing = True
        self.confirm_button.set_enabled(False)
        self._say_pairing(f"Pairing with {current['name']}…")
        discovery = self.discovery

        def work():
            try:
                result = discovery.pair(current, code)
            except pairing.PairingError as exc:
                result = exc
            except Exception as exc:
                self.logger.exception("pairing failed")
                result = pairing.PairingError(str(exc))
            AppHelper.callAfter(self._pairing_finished, current, result)

        threading.Thread(target=work, name="pair", daemon=True).start()

    @objc.python_method
    def _pairing_finished(self, pc, result):
        self._pairing = False
        self.confirm_button.set_enabled(self.chosen_pc is not None)
        name = pc["name"]
        if isinstance(result, pairing.PairingError):
            reason = str(result)
            if reason == pairing.ERROR_NOT_PAIRING:
                self._say_pairing(f"{name} is not showing a code. Press Pair a Mac on it, then try again.", "fault")
            elif reason == pairing.ERROR_REFUSED:
                self._say_pairing("That code was not accepted, and the PC has cancelled it. Press Pair a Mac there for a fresh one.", "fault")
            elif reason == "no_answer":
                self._say_pairing(f"{name} did not answer. Check both machines are on the same network, then try again.", "fault")
            else:
                self._say_pairing(f"Pairing failed: {reason}", "fault")
            return
        raw = config_to_raw(self.controller.cfg)
        raw["host"] = pc["address"]
        raw["port"] = pc["port"]
        raw["auth_token"] = result
        raw["pc_name"] = name
        # The Mac has just exchanged packets with the PC, so its ARP entry is fresh.
        raw["mac_address"] = lookup_mac(pc["address"]) or ""
        try:
            cfg = self.settings_store.save(raw)
        except SettingsError as exc:
            self._say_pairing(f"Paired, but the settings could not be saved: {exc}", "fault")
            return
        self.code_boxes.clear()
        self.chosen_pc = None
        self._pcs_key = None
        self._repairing = False
        self._load(config_to_raw(cfg))
        self.controller.update_config(cfg)
        self._say("Paired with " + name + ". Connecting…", "signal")
        self.logger.info("paired with %s at %s", name, pc["address"])

    @objc.python_method
    def _persist_mac(self, _mac):
        """The controller has already put the learned address on cfg; this writes it down."""
        try:
            self.settings_store.save(config_to_raw(self.controller.cfg))
        except SettingsError as exc:
            self.logger.warning("hardware address not saved: %s", exc)

    @objc.python_method
    def _crossing_state_sentence(self):
        controller = self.controller
        if not controller.crossing.armed:
            return "Only the shortcut is switched on; there is nothing to pause."
        if controller.crossing_paused:
            return "Paused. Edges, corners and the notch do nothing until you resume; the shortcut still works."
        if controller.full_screen_app is not None:
            return (
                f"Off while {controller.full_screen_app} is full screen, so the pointer stays put at "
                "the edges; the shortcut still works."
            )
        return "On. Pause it to lean on an edge without switching."

    @objc.python_method
    def _permission(self, status, button, granted):
        status.set("Granted" if granted else "Required", ink="signal" if granted else "amber")
        button.set_title("Granted" if granted else "Grant")
        button.set_enabled(not granted)

    @objc.python_method
    def refresh(self):
        controller = self.controller
        access = accessibility_granted()
        listening = input_monitoring_granted()
        self._permission(self.access_status, self.access_button, access)
        self._permission(self.input_status, self.input_button, listening)
        if access and listening and not controller.input_ready:
            now = time.monotonic()
            if now - self.last_capture_attempt >= CAPTURE_RETRY_INTERVAL_SECONDS:
                self.last_capture_attempt = now
                controller.start_input_capture()
        if controller.input_ready:
            self.capture_status.set("Input capture ready.", ink="signal")
        elif access and listening:
            detail = controller.input_error
            self.capture_status.set(f"Retrying input capture… {detail}" if detail else "Retrying input capture…", ink="fault")
        else:
            self.capture_status.set(
                "Beamer needs both, granted separately. macOS only delivers keyboard events to a process "
                "started after the grant, so relaunch Beamer once you have given them.",
                ink="ink_2",
            )

        sentence = self._ways_in_sentence()
        self.ways_note.set(sentence + "." if sentence else "No way in is switched on. Choose one below.")
        state = link_state.describe(controller)
        self._refresh_paired(state)
        self.sidebar.set_link(state, link_state.peer_name(controller.cfg))
        self.sidebar.set_dots(pages.dots(access, listening, state.key))
        self.link_led.set(state.led, state.blink)
        self.link_tag.set(state.tag)
        self.state_word.set(state.word, ink=state.tone)
        self.state_detail.set(state.detail)

        round_trip = controller.round_trip_ms
        if controller.redirecting:
            if round_trip is not None:
                self.latency.append(round_trip)
        else:
            self.latency.clear()
        live = controller.redirecting and round_trip is not None
        self.round_trip.value.set(str(round_trip) if live else "—", ink="signal" if live else "ink")
        self.spark.samples = list(self.latency)
        self.spark.live = controller.redirecting
        self.spark.setNeedsDisplay_(True)
        cfg = controller.cfg
        self._show_peer()

        self.pause_button.set_title("Resume crossing" if controller.crossing_paused else "Pause crossing")
        self.pause_button.set_style("primary" if controller.crossing_paused else "plain")
        self.pause_button.set_enabled(controller.crossing.armed)
        self.crossing_state.set(self._crossing_state_sentence())
        has_notch = controller.notch_range is not None
        if has_notch != self.has_notch:
            self.has_notch = has_notch
            self._reflect()
        self.selector.set("windows" if controller.redirecting else "mac")
        if controller.redirecting:
            self.toggle_button.set_title("Return input to Mac")
        elif controller.waking:
            self.toggle_button.set_title("Waking Windows…")
        elif controller.can_wake:
            self.toggle_button.set_title("Wake Windows")
        else:
            self.toggle_button.set_title("Send input to Windows")
        self.toggle_button.set_style("live" if controller.redirecting or controller.windows_locked else "primary")
        self.toggle_button.set_enabled(
            controller.input_ready
            and not controller.waking
            and (controller.connected or controller.can_wake)
        )
        mac = cfg.mac_address
        self.wake_state.set(mac if mac else "Not yet learned", ink="ink" if mac else "ink_3")
        self.wake_hint.set(
            "Crossing to the PC while it sleeps sends a wake-up packet and waits for it."
            if mac
            else "Read from the network the first time this Mac connects; nothing to type."
        )
        self._refresh_pcs()


class StatusItemClick(AppKit.NSObject):
    """Splits the menu bar item's clicks: left opens the window, right opens the menu.

    An NSStatusItem with a menu attached hands it every click, and rumps attaches one, so the
    menu is detached at startup and put back for the moment a right click needs it."""

    def initWithTray_(self, tray):
        self = objc.super(StatusItemClick, self).init()
        if self is None:
            return None
        self.tray = tray
        return self

    def clicked_(self, _sender):
        item = self.tray.status_item_view
        event = AppKit.NSApp.currentEvent()
        right = event is not None and (
            event.type() == AppKit.NSEventTypeRightMouseUp
            or event.modifierFlags() & AppKit.NSEventModifierFlagControl
        )
        if not right:
            self.tray.control_window.show()
            return
        item.setMenu_(self.tray.detached_menu)
        item.button().performClick_(None)
        item.setMenu_(None)


class _LaunchWatch(AppKit.NSObject):
    """A login item takes no arguments, so a login launch is recognised instead: macOS marks it
    as not the default launch, and that is the cue to stay in the menu bar."""

    def initWithTray_(self, tray):
        self = objc.super(_LaunchWatch, self).init()
        self.tray = tray
        AppKit.NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "launched:", AppKit.NSApplicationDidFinishLaunchingNotification, None
        )
        return self

    def launched_(self, note):
        info = note.userInfo() or {}
        default = info.get("NSApplicationLaunchIsDefaultLaunchKey")
        if default is not None and not bool(default):
            self.tray.hidden = True


class TrayApp(rumps.App):
    def __init__(self, controller, settings_store, logger, hidden=False):
        self.hidden = hidden
        self.launch_watch = _LaunchWatch.alloc().initWithTray_(self)
        self.controller = controller
        self.settings_store = settings_store
        self.logger = logger
        self.control_window = ControlWindow.alloc().initWithController_settingsStore_logger_(
            controller, settings_store, logger
        )
        self.control_window.quit_handler = self.quit_app
        install_main_menu(self.control_window)
        self.gesture_overlay = GestureOverlay(controller, logger)
        self.edge_glow = EdgeGlow(controller, logger)
        self.notch_island = NotchIsland(controller, logger)
        self.notch_beam = NotchBeam(controller, logger)
        self.haptics = Haptics(logger)
        self.control_window.preview = self.edge_glow.preview
        self.control_window.haptics = self.haptics
        self.controller.on_user_alert = self.notify_user
        self.controller.on_crossing = self.crossing_feedback
        self.controller.on_arrangement = self._arrangement
        self.controller.on_mac_learned = lambda mac: AppHelper.callAfter(self.control_window._persist_mac, mac)
        # The other direction, listening from the moment Beamer opens: the PC
        # may want to send its own keyboard here before this Mac has ever
        # crossed the other way.
        self.windows_input = WindowsInput(controller, logger, arrangement_callback=self._arrangement)
        self.control_window.windows_input = self.windows_input
        self.windows_input.sync(controller.cfg)
        self.discovery = pairing.Discovery(logger=logger)
        self.control_window.discovery = self.discovery
        self.discovery.start()
        self._notch_failed = False
        header = rumps.MenuItem(f"Beamer {VERSION}", callback=None)
        self.status_item = rumps.MenuItem("Starting", callback=None)
        self.toggle_item = rumps.MenuItem("Send input to Windows", callback=self.toggle_redirect)
        self.pause_item = rumps.MenuItem("Pause crossing", callback=self.toggle_pause)
        # One tick per direction, so either can be switched off while the other keeps working.
        self.send_item = rumps.MenuItem("This Mac drives Windows", callback=self.toggle_send_to_windows)
        self.receive_item = rumps.MenuItem("Windows drives this Mac", callback=self.toggle_windows_drives)
        self._symbol = None
        super().__init__(
            "Beamer",
            title="Beamer • Local",
            menu=[
                header,
                rumps.separator,
                self.status_item,
                self.toggle_item,
                self.pause_item,
                rumps.separator,
                self.send_item,
                self.receive_item,
                rumps.separator,
                rumps.MenuItem("Settings…", callback=self.open_window),
                rumps.MenuItem("Reload configuration", callback=self.reload_config),
                rumps.separator,
                rumps.MenuItem("About Beamer", callback=self.show_about),
                rumps.MenuItem("Quit Beamer", callback=self.quit_app),
            ],
            quit_button=None,
        )
        self.status_timer = rumps.Timer(self.refresh_status, 0.4)
        self.startup_timer = rumps.Timer(self.show_on_startup, 0.2)
        # Its own timer, slower than the status tick: the window list is a window-server call,
        # and once a second is the cache the tap thread reads from.
        self.full_screen_timer = rumps.Timer(self.check_full_screen, FULL_SCREEN_CHECK_INTERVAL_SECONDS)
        self.status_timer.start()
        self.startup_timer.start()
        self.full_screen_timer.start()

    def _arrangement(self, mac_edge, set_at):
        """An arrangement from the PC, over either link, applied on the main
        thread -- it writes the settings file and redraws the window."""
        AppHelper.callAfter(self.control_window.apply_arrangement, mac_edge, set_at)

    def show_on_startup(self, _timer):
        self.startup_timer.stop()
        self.split_clicks()
        if not self.hidden:
            self.control_window.show()

    def split_clicks(self):
        """Runs once the status item exists, which is after rumps has started the app."""
        self.status_item_view = self._nsapp.nsstatusitem
        self.detached_menu = self.status_item_view.menu()
        self.status_item_view.setMenu_(None)
        self.click_handler = StatusItemClick.alloc().initWithTray_(self)
        button = self.status_item_view.button()
        button.setTarget_(self.click_handler)
        button.setAction_("clicked:")
        button.sendActionOn_(AppKit.NSEventMaskLeftMouseUp | AppKit.NSEventMaskRightMouseUp)

    def refresh_status(self, _timer):
        self.windows_input.sync(self.controller.cfg)
        self.measure_notch()
        self.control_window.refresh()
        self.gesture_overlay.sync()
        controller = self.controller
        held = controller.crossing.armed and (controller.crossing_paused or controller.full_screen_app is not None)
        self.set_menu_bar_symbol(
            "windows" if controller.redirecting or controller.receiving else "held" if held else "local"
        )
        if controller.redirecting:
            self.toggle_item.title = "Return input to Mac"
        else:
            self.toggle_item.title = "Send input to Windows"
        self.pause_item.title = "Resume crossing" if controller.crossing_paused else "Pause crossing"
        self.send_item.state = int(controller.cfg.send_to_windows)
        self.receive_item.state = int(controller.cfg.allow_windows_to_drive)
        self.status_item.title = link_state.describe(controller).word

    def set_menu_bar_symbol(self, state):
        """One template glyph per state instead of words. rumps only takes an icon as a file
        path, so the NSImage goes in by hand; _icon_nsimage is what it reads when the status
        item is first built, before nsstatusitem exists."""
        if state != self._symbol:
            self._symbol = state
            self._icon_nsimage = menu_bar_glyph(state)
            self._title = ""
            try:
                self._nsapp.setStatusBarIcon()
            except AttributeError:
                pass
        # rumps decides the status item is empty by reading the deprecated
        # NSStatusItem.image(), which is nil even while the image is on screen,
        # so it keeps putting the app name back as the title. Clear it instead
        # of fighting it.
        try:
            item = self._nsapp.nsstatusitem
        except AttributeError:
            return
        if item.title():
            item.setTitle_("")

    def open_window(self, _sender):
        self.control_window.show()

    def toggle_send_to_windows(self, _sender):
        self._set_direction(send_to_windows=not self.controller.cfg.send_to_windows)

    def toggle_windows_drives(self, _sender):
        self._set_direction(allow_windows_to_drive=not self.controller.cfg.allow_windows_to_drive)

    def _set_direction(self, **change):
        try:
            cfg = self.settings_store.save(config_to_raw(replace(self.controller.cfg, **change)))
        except SettingsError as exc:
            self.logger.warning("direction not saved: %s", exc)
            self.notify_user("Beamer", f"Could not save the change: {exc}")
            return
        self.controller.update_config(cfg)
        self.windows_input.sync(cfg)
        self.logger.info("directions: this Mac drives Windows %s, Windows drives this Mac %s",
                         "on" if cfg.send_to_windows else "off", "on" if cfg.allow_windows_to_drive else "off")
        self.refresh_status(None)

    def reload_config(self, _sender):
        """Re-reads config.json, for the times it was edited outside the window."""
        try:
            cfg = self.settings_store.load()
        except SettingsError as exc:
            self.logger.warning("configuration not reloaded: %s", exc)
            self.notify_user("Configuration not reloaded", str(exc))
            return
        self.control_window._load(config_to_raw(cfg))
        self.controller.update_config(cfg)
        self.notify_user("Configuration reloaded", "Beamer is using the config on disk.")

    def show_about(self, _sender):
        show_about_panel()

    def measure_notch(self):
        """Re-read on every tick so plugging a display in above the MacBook, which moves the
        notch off the top of the desktop, is noticed without a restart."""
        if self._notch_failed:
            return
        try:
            self.controller.notch_range = notch_x_range()
        except Exception:
            self._notch_failed = True
            self.controller.notch_range = None
            self.logger.exception("could not measure the notch; the notch method is off")

    def check_full_screen(self, _timer):
        """Feeds the controller the name of a full-screen frontmost app, or None. A failure
        stops the check for the run rather than logging once a second; crossing then simply
        stays on, as it was before this existed."""
        try:
            self.controller.full_screen_app = full_screen_app()
        except Exception:
            self.controller.full_screen_app = None
            self.full_screen_timer.stop()
            self.logger.exception("could not tell whether an app is full screen; crossing stays on")

    def toggle_pause(self, _sender):
        self.controller.crossing_paused = not self.controller.crossing_paused
        self.refresh_status(None)

    def crossing_feedback(self, kind, step):
        """Wired to controller.on_crossing, called off the event-tap and ack threads. Only the
        hop to the main thread happens here; haptics and the glow both touch AppKit."""
        AppHelper.callAfter(self._crossing_feedback_main, kind, step)

    def _crossing_feedback_main(self, kind, step):
        try:
            feel = self.controller.cfg.crossing
            if feel["haptics"]:
                if kind == "tick":
                    if crossing.tick_fires(feel["haptic_steps"], step.pressure):
                        self.haptics.tick(feel["haptic_feel"])
                elif kind in ("cross", "arrive"):
                    self.haptics.thud()
            if feel["glow"]:
                if step.via == "notch":
                    notch = self.notch_beam if feel["notch_style"] == "beam" else self.notch_island
                    notch.update(kind)
                else:
                    self.edge_glow.update(kind, step)
        except Exception:
            self.logger.exception("crossing feedback failed")

    def notify_user(self, title, message):
        """Wired to controller.on_user_alert, which fires on the event-tap and
        connection threads. AppKit is main-thread only, so the work hops
        there like every other controller callback in this class."""
        AppHelper.callAfter(self._notify_user_main, title, message)

    def _notify_user_main(self, title, message):
        try:
            AppKit.NSBeep()
        except Exception:
            self.logger.exception("failed to beep for a user alert")
        try:
            rumps.notification("Beamer", title, message)
        except Exception:
            self.logger.exception("failed to show a user notification")

    def toggle_redirect(self, _sender):
        self.control_window.toggleRedirect_(None)

    def quit_app(self, _sender=None):
        self.status_timer.stop()
        self.discovery.stop()
        self.windows_input.stop()
        self.controller.stop()
        rumps.quit_application()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Beamer macOS sender")
    parser.add_argument(
        "--config",
        default=None,
        help="config path; defaults to ~/Library/Application Support/Beamer/config.json",
    )
    parser.add_argument("--hidden", action="store_true", help="start in the menu bar without opening the window")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if sys.platform != "darwin":
        raise SystemExit("Beamer must run on macOS")
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        return
    AppKit.NSApplication.sharedApplication()
    theme.init_fonts()
    logger = configure_logging()
    # Which faces actually carried the window: the only way to tell the bundled copies failed to
    # register is to say what was used instead.
    logger.info("type: %s / %s", theme.sans(), theme.mono())
    if args.config is None:
        migrate_legacy_config()
    settings_store = SettingsStore(args.config)
    try:
        cfg = settings_store.load()
    except SettingsError as exc:
        logger.warning("settings not loaded: %s", exc)
        cfg = editable_default_config()
    controller = WakingController(cfg, logger=logger)
    app = TrayApp(controller, settings_store, logger, hidden=args.hidden)
    controller.start()
    try:
        app.run()
    finally:
        controller.stop()
        instance_lock.close()


if __name__ == "__main__":
    main()
