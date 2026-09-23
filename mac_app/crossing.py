"""The crossing engine: pointer pressure against the outer edge of the Mac desktop.

Pure arithmetic, no AppKit and no Quartz, so it runs under unittest on any machine. bridge.py
feeds it every local mouse movement while the crossing methods are armed and acts on what comes
back; kvm_bridge_app.py reads pressure for the glow. Coordinates are Quartz global points
(top-left origin, the space CGEventGetLocation and CGDisplayBounds share), and `bounds` is the
union of every display as (left, top, right, bottom) with right and bottom exclusive.

Pressure is measured in raw pointer delta units, the same "pixels of travel" the trackpad reports,
and decays at a rate that empties a full push in DECAY_S once the outward movement stops. That one
mechanism is what keeps a slow lean against the edge from ever building a switch.
"""

from dataclasses import dataclass

EDGES = ("left", "right", "top", "bottom")
CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")
METHODS = ("shortcut", "edge", "corner", "notch")
NOTCH_STYLES = ("beam", "island")
HAPTIC_FEELS = ("light", "medium", "firm")
HAPTIC_STEPS = ("quarters", "halves", "breakthrough")
GLOW_STYLES = ("glow", "beam")
# The names of tokens.PALETTES, spelled out because this module stays importable without the root.
GLOW_COLOURS = ("signal", "colourful", "ocean", "sunset", "mono")
OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}

DEFAULT_CROSSING = {
    "methods": ["shortcut", "edge"],
    "edge": "right",
    "corner": "top_right",
    "resistance_px": 120,
    "haptics": True,
    "glow": True,
    "notch_style": "beam",
    "notch_after_ms": 1200,
    "haptic_feel": "medium",
    "haptic_steps": "quarters",
    "glow_style": "glow",
    "glow_colour": "signal",
    "block_while_dragging": True,
    # Unix seconds at the moment this Mac last changed the arrangement -- which
    # edge leads to the PC. Either machine may change it, so when two ends meet
    # holding different answers the newer stamp wins. Never read by the engine;
    # it lives here so it is saved and loaded with the rest of the crossing.
    "arrangement_set_at": 0,
}

DECAY_S = 0.4
CORNER_PX = 8.0
# How close to the last pixel of the desktop counts as touching it. The cursor's reported
# location at an edge is fractional on a Retina display, so an exact comparison misses.
EDGE_TOLERANCE = 1.5
# Pressure below this passes events through untouched: a lean of a pixel or two per event
# would otherwise alternate between pinning and releasing the pointer at the trackpad's rate.
HOLD_MIN_PX = 3.0


def tick_fires(steps, pressure):
    """Whether a quarter tick is felt under `crossing.haptic_steps`, given the pressure it fired at:
    every quarter, only the one at halfway, or none, leaving just the thud at breakthrough."""
    if steps == "quarters":
        return True
    if steps == "halves":
        return min(3, int(4 * pressure + 1e-9)) == 2
    return False


@dataclass
class Step:
    """What the bridge does with one movement event. `hold` means swallow it and warp the
    pointer back to `pin`; `crossed` means hand input to Windows, arriving at `edge` (a Windows
    edge) at `offset` along it. `mac_edge` and `region` describe the strip being pushed, for
    the glow, and `via` names the method that owns that strip, so the notch can get its own
    feedback; `pressure` is the fraction of the way to breakthrough."""

    pressure: float = 0.0
    hold: bool = False
    pin: tuple = None
    tick: bool = False
    crossed: bool = False
    edge: str = None
    offset: float = None
    mac_edge: str = None
    region: tuple = None
    via: str = None


class CrossingEngine:
    def __init__(
        self,
        methods=("shortcut", "edge"),
        edge="right",
        corner="top_right",
        resistance_px=120,
        block_while_dragging=True,
    ):
        self.methods = frozenset(methods)
        self.edge = edge
        self.corner = corner
        self.resistance_px = float(resistance_px)
        self.block_while_dragging = block_while_dragging
        self.reset()

    @classmethod
    def from_config(cls, crossing):
        return cls(
            methods=crossing["methods"],
            edge=crossing["edge"],
            corner=crossing["corner"],
            resistance_px=crossing["resistance_px"],
            block_while_dragging=crossing["block_while_dragging"],
        )

    @property
    def armed(self):
        return bool(self.methods & {"edge", "corner", "notch"})

    def reset(self):
        self.touching = False
        self.pressure = 0.0
        self.pin = None
        self.mac_edge = None
        self.region = None
        self._quarter_reached = 0
        self._last_at = None
        self._last_x = None
        self._last_y = None

    def home_edge(self, mac_edge=None):
        """The Windows edge the pointer comes home through: opposite the Mac edge it left by or,
        for a shortcut switch, opposite whichever pointer method is on. None when only the
        shortcut is on. The configured `edge` keeps its value while the edge method is off, so
        reading it unconditionally armed a Windows edge nobody had enabled and left the notch's
        own way home dead after every shortcut switch."""
        if mac_edge is None:
            if "edge" in self.methods:
                mac_edge = self.edge
            elif "notch" in self.methods:
                mac_edge = "top"
            elif "corner" in self.methods:
                mac_edge = self.corner.split("_")[1]
            else:
                return None
        return OPPOSITE[mac_edge]

    def pressure_at(self, now):
        """Pressure as a fraction, decayed to `now` without recording anything — for the glow,
        which has to keep fading after the last event arrives."""
        if self.resistance_px <= 0 or self._last_at is None:
            return 0.0
        remaining = self.pressure - self._decay(now - self._last_at)
        return max(0.0, min(1.0, remaining / self.resistance_px))

    def feed(self, x, y, dx, dy, bounds, now, notch_range=None, dragging=False):
        if self._last_at is not None:
            self.pressure = max(0.0, self.pressure - self._decay(now - self._last_at))
        self._last_at = now
        previous_x, previous_y = self._last_x, self._last_y
        self._last_x, self._last_y = x, y
        if dragging and self.block_while_dragging:
            self.touching = False
            return self._release()

        target = self._target(x, y, bounds, notch_range)
        # Whether the pointer is at an armed region at all, whatever the pressure: a slow push
        # drains to nothing between events and releases, but is still against the edge.
        self.touching = target is not None
        if target is None:
            return self._release()
        mac_edge, region, diagonal, via = target
        outward, inward = self._push(mac_edge, diagonal, x, y, dx, dy, previous_x, previous_y, bounds)
        before = self.pressure
        self.pressure = max(0.0, self.pressure + outward - inward)
        if self.pressure <= 0.0:
            return self._release()
        if self.pin is None:
            self.pin = (x, y)
        self.mac_edge = mac_edge
        self.region = region

        if outward > 0.0 and self.pressure >= self.resistance_px:
            step = Step(
                pressure=1.0,
                crossed=True,
                edge=OPPOSITE[mac_edge],
                offset=self._offset(mac_edge, self.pin, bounds),
                mac_edge=mac_edge,
                region=region,
                via=via,
            )
            self.reset()
            return step
        # Ticks are counted against the highest quarter this push has reached, not the
        # previous reading: decay between two events can drop the reading back under a
        # boundary, and comparing readings would then fire the same tick twice.
        quarter = self._quarter(self.pressure)
        tick = quarter > self._quarter_reached
        self._quarter_reached = max(self._quarter_reached, quarter)
        return Step(
            pressure=self._fraction(self.pressure),
            hold=before >= HOLD_MIN_PX,
            pin=self.pin,
            tick=tick,
            mac_edge=mac_edge,
            region=region,
            via=via,
        )

    @staticmethod
    def arrival_point(edge, offset, bounds, inset=2.0):
        """Where the pointer lands when input comes home through a Mac `edge`, `offset` of the
        way along it, a couple of points inside so the arrival itself is not already a push."""
        left, top, right, bottom = bounds
        offset = max(0.0, min(1.0, float(offset)))
        if edge in ("left", "right"):
            y = top + offset * (bottom - 1 - top)
            x = left + inset if edge == "left" else right - 1 - inset
        else:
            x = left + offset * (right - 1 - left)
            y = top + inset if edge == "top" else bottom - 1 - inset
        return (x, y)

    def _decay(self, elapsed):
        if elapsed <= 0 or self.resistance_px <= 0:
            return 0.0
        return self.resistance_px * elapsed / DECAY_S

    def _release(self):
        self.pressure = 0.0
        self.pin = None
        self.mac_edge = None
        self.region = None
        self._quarter_reached = 0
        return Step()

    def _fraction(self, pressure):
        if self.resistance_px <= 0:
            return 0.0
        return max(0.0, min(1.0, pressure / self.resistance_px))

    def _quarter(self, pressure):
        if self.resistance_px <= 0:
            return 0
        return min(3, int(4 * pressure / self.resistance_px))

    def _target(self, x, y, bounds, notch_range):
        """Which armed region the pointer is touching, as (mac_edge, region, diagonal, method). The
        corner wins over the edge it sits on, since its box is inside that edge's strip."""
        left, top, right, bottom = bounds
        x_max, y_max = right - 1, bottom - 1
        at = {
            "left": x <= left + EDGE_TOLERANCE,
            "right": x >= x_max - EDGE_TOLERANCE,
            "top": y <= top + EDGE_TOLERANCE,
            "bottom": y >= y_max - EDGE_TOLERANCE,
        }
        if "corner" in self.methods:
            vertical, horizontal = self.corner.split("_")
            near_x = x <= left + CORNER_PX if horizontal == "left" else x >= x_max - CORNER_PX
            near_y = y <= top + CORNER_PX if vertical == "top" else y >= y_max - CORNER_PX
            if near_x and near_y and (at[horizontal] or at[vertical]):
                box_x = left if horizontal == "left" else x_max - CORNER_PX + 1
                box_y = top if vertical == "top" else y_max - CORNER_PX + 1
                return horizontal, (box_x, box_y, CORNER_PX, CORNER_PX), vertical, "corner"
        if "edge" in self.methods and at[self.edge]:
            return self.edge, self._strip(self.edge, bounds), None, "edge"
        if "notch" in self.methods and notch_range is not None and at["top"]:
            notch_left, notch_right = notch_range
            if notch_left <= x <= notch_right:
                return "top", (notch_left, top, notch_right - notch_left, 1), None, "notch"
        return None

    @staticmethod
    def _strip(edge, bounds):
        left, top, right, bottom = bounds
        if edge == "left":
            return (left, top, 1, bottom - top)
        if edge == "right":
            return (right - 1, top, 1, bottom - top)
        if edge == "top":
            return (left, top, right - left, 1)
        return (left, bottom - 1, right - left, 1)

    def _push(self, mac_edge, diagonal, x, y, dx, dy, previous_x, previous_y, bounds):
        """Outward and inward travel for this event. Against a flat edge the OS has already
        clamped the location, so the delta itself is the push once the pointer is there; on the
        event that first reaches the edge only the overshoot past it counts, so a pointer that
        merely arrives at the edge does not start with a head of pressure it never earned."""
        left, top, right, bottom = bounds
        out_x = self._axis(mac_edge, x, dx, previous_x, left, right - 1)
        if diagonal is None:
            out = out_x if mac_edge in ("left", "right") else self._axis(mac_edge, y, dy, previous_y, top, bottom - 1)
            return max(0.0, out), max(0.0, -out)
        out_y = self._axis(diagonal, y, dy, previous_y, top, bottom - 1)
        if out_x > 0 and out_y > 0:
            return (out_x * out_x + out_y * out_y) ** 0.5, 0.0
        inward = (min(0.0, out_x) ** 2 + min(0.0, out_y) ** 2) ** 0.5
        return 0.0, inward

    @staticmethod
    def _axis(edge, position, delta, previous, low, high):
        """Signed outward travel along one axis, positive when moving off the desktop."""
        if edge in ("left", "top"):
            outward = -delta
            if previous is not None and previous > low + EDGE_TOLERANCE:
                outward = min(outward, low - (previous + delta))
        else:
            outward = delta
            if previous is not None and previous < high - EDGE_TOLERANCE:
                outward = min(outward, (previous + delta) - high)
        return outward

    @staticmethod
    def _offset(mac_edge, point, bounds):
        left, top, right, bottom = bounds
        x, y = point
        if mac_edge in ("left", "right"):
            span = bottom - 1 - top
            fraction = (y - top) / span if span > 0 else 0.0
        else:
            span = right - 1 - left
            fraction = (x - left) / span if span > 0 else 0.0
        return round(max(0.0, min(1.0, fraction)), 4)
