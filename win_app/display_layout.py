"""Screen inventory validation and crossing routes, independent of Qt/network IO."""
import math
from dataclasses import replace
import return_edge as geometry

MESSAGE = "windows_displays"


def inventory(value):
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("Invalid screen inventory")
    result, seen = [], set()
    for screen in value:
        if not isinstance(screen, dict):
            raise ValueError("Invalid screen")
        name = screen.get("id")
        if not isinstance(name, str) or not name or len(name) > 128 or name in seen:
            raise ValueError("Invalid screen identity")
        seen.add(name)
        item = {"id": name}
        for key in ("x", "y", "width", "height"):
            number = screen.get(key)
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise ValueError("Invalid screen coordinates")
            if abs(number) > 100000 or (key in ("width", "height") and number < 1):
                raise ValueError("Screen coordinates out of range")
            item[key] = int(number)
        result.append(item)
    return result


def validate_layout(value):
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError("Invalid screen layout")
    result, seen = [], set()
    for raw in value:
        if not isinstance(raw, dict) or raw.get("owner") not in ("local", "peer"):
            raise ValueError("Invalid screen owner")
        item = inventory([raw])[0]
        item["owner"] = raw["owner"]
        key = (item["owner"], item["id"])
        if key in seen:
            raise ValueError("Duplicate screen in layout")
        seen.add(key)
        result.append(item)
    return result


def reverse_layout(layout):
    return [dict(item, owner="peer" if item["owner"] == "local" else "local")
            for item in validate_layout(layout)]


def contacts(layout):
    """Only touching screen edges cross; gaps, overlaps and same-PC edges do not."""
    local = [s for s in layout if s["owner"] == "local"]
    peer = [s for s in layout if s["owner"] == "peer"]
    result = []
    for a in local:
        for b in peer:
            for edge, distance, vertical in (
                ("right", a["x"] + a["width"] - b["x"], True),
                ("left", a["x"] - b["x"] - b["width"], True),
                ("bottom", a["y"] + a["height"] - b["y"], False),
                ("top", a["y"] - b["y"] - b["height"], False),
            ):
                axis, size = ("y", "height") if vertical else ("x", "width")
                start, end = max(a[axis], b[axis]), min(a[axis]+a[size], b[axis]+b[size])
                if abs(distance) <= 1 and end > start:
                    result.append((a, b, edge, start, end))
    return result


def overlapping(layout):
    for index, a in enumerate(layout):
        for b in layout[index+1:]:
            if (max(a["x"], b["x"]) < min(a["x"]+a["width"], b["x"]+b["width"])
                    and max(a["y"], b["y"]) < min(a["y"]+a["height"], b["y"]+b["height"])):
                return True
    return False


def arrival(displays, screen_id, edge, offset):
    screen = next((s for s in displays if s["id"] == screen_id), None)
    if screen is None:
        return None
    return geometry.arrival_position([geometry.Rect(screen["x"], screen["y"], screen["width"], screen["height"])], edge, offset)


class ScreenRoutes:
    """Pressure models per touching pair; physical monitor geometry is authoritative."""
    def __init__(self, layout, displays, resistance):
        self.layout = validate_layout(layout)
        self.displays = {s["id"]: s for s in inventory(displays)}
        self.models = {}
        self.armed = True
        self.edge = "right"
        self.target_display = None
        self.routes = contacts(self.layout)
        for a, b, edge, start, end in self.routes:
            self.models[(a["id"], b["id"], edge)] = geometry.ReturnEdge(edge, resistance)

    def reset(self):
        for model in self.models.values():
            model.reset()

    def feed(self, monitors, pointer, dx, dy):
        if not self.armed:
            return geometry.Outcome(geometry.PASS)
        for a, b, edge, start, end in self.routes:
            physical = self.displays.get(a["id"])
            if physical is None:
                continue
            rect = geometry.Rect(physical["x"], physical["y"], physical["width"], physical["height"])
            axis, size, coordinate = ("y", "height", pointer[1]) if edge in ("left", "right") else ("x", "width", pointer[0])
            fraction = (coordinate - physical[axis]) / physical[size]
            along = a[axis] + fraction * a[size]
            model = self.models[(a["id"], b["id"], edge)]
            if not (rect.x <= pointer[0] <= rect.right and rect.y <= pointer[1] <= rect.bottom and start <= along < end):
                model.reset()
                continue
            # Do not create a portal across an internal physical edge of this PC.
            outcome = model.feed(monitors, pointer, dx, dy)
            if outcome.action == geometry.PASS:
                continue
            self.edge, self.target_display = edge, b["id"]
            if outcome.action == geometry.CROSS:
                self.armed = False
                outcome = replace(outcome, offset=max(0, min(1, (along-b[axis])/b[size])))
            return outcome
        return geometry.Outcome(geometry.PASS)
