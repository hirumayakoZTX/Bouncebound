"""Swept circle/rectangle geometry with no display or combat dependencies."""

from dataclasses import dataclass
from math import hypot, isfinite, sqrt


EPSILON = 1e-9
CONTACT_SLOP = 1e-6
Point = tuple[float, float]


@dataclass(frozen=True)
class Bounds:
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        if (not all(isfinite(v) for v in (self.left, self.top, self.right, self.bottom))
                or self.left >= self.right or self.top >= self.bottom):
            raise ValueError("Bounds must be finite with positive width and height")

    def inset(self, radius: float) -> "Bounds":
        return Bounds(self.left + radius, self.top + radius,
                      self.right - radius, self.bottom - radius)

    def contains(self, point: Point, tolerance: float = EPSILON) -> bool:
        x, y = point
        return (self.left - tolerance <= x <= self.right + tolerance
                and self.top - tolerance <= y <= self.bottom + tolerance)


@dataclass(frozen=True)
class Target:
    """A reflecting damage target or a non-reflecting, zero-damage trigger."""

    target_id: int
    bounds: Bounds
    reflects: bool = True


@dataclass(frozen=True)
class Contact:
    time: float
    normal: Point
    position: Point
    is_impact: bool = True


def is_approaching(velocity: Point, normal: Point) -> bool:
    """Require meaningful inward normal speed, ignoring floating-point noise."""
    normal_speed = velocity[0] * normal[0] + velocity[1] * normal[1]
    return normal_speed < -EPSILON * max(1.0, hypot(*velocity))


def circle_overlaps(position: Point, radius: float, bounds: Bounds) -> bool:
    x, y = position
    nearest_x = min(max(x, bounds.left), bounds.right)
    nearest_y = min(max(y, bounds.top), bounds.bottom)
    return hypot(x - nearest_x, y - nearest_y) <= radius + CONTACT_SLOP


def sweep_circle(
    position: Point, velocity: Point, radius: float, bounds: Bounds, duration: float
) -> Contact | None:
    """Find first contact with the rectangle's exact rounded expansion.

    Face crossings and circular corner crossings are tested separately, avoiding
    the false corner hits produced by a simple expanded rectangular hitbox.
    Initial penetration uses minimum escape distance, with X before Y on ties.
    Penetration returns a recovery contact, not evidence of a new impact. Surface
    contacts, including time-zero contacts, require inward normal velocity.
    """
    x, y = position
    vx, vy = velocity
    nearest = (min(max(x, bounds.left), bounds.right),
               min(max(y, bounds.top), bounds.bottom))
    dx, dy = x - nearest[0], y - nearest[1]
    distance = hypot(dx, dy)
    if distance <= radius + EPSILON:
        if distance > EPSILON:
            normal = (dx / distance, dy / distance)
            corrected = (nearest[0] + radius * normal[0], nearest[1] + radius * normal[1])
        else:
            _, normal, corrected = min((
                (x - bounds.left + radius, (-1.0, 0.0), (bounds.left - radius, y)),
                (bounds.right - x + radius, (1.0, 0.0), (bounds.right + radius, y)),
                (y - bounds.top + radius, (0.0, -1.0), (x, bounds.top - radius)),
                (bounds.bottom - y + radius, (0.0, 1.0), (x, bounds.bottom + radius)),
            ), key=lambda item: item[0])
        if distance < radius - EPSILON:
            return Contact(0.0, normal, corrected, is_impact=False)
        if is_approaching(velocity, normal):
            return Contact(0.0, normal, corrected)
        return None

    contacts = []

    def add(time: float, normal: Point) -> None:
        if -EPSILON <= time <= duration + EPSILON and is_approaching(velocity, normal):
            time = min(duration, max(0.0, time))
            contacts.append(Contact(time, normal, (x + vx * time, y + vy * time)))

    if vx:
        plane, normal = ((bounds.left - radius, (-1.0, 0.0)) if vx > 0
                         else (bounds.right + radius, (1.0, 0.0)))
        time = (plane - x) / vx
        if bounds.top - EPSILON <= y + vy * time <= bounds.bottom + EPSILON:
            add(time, normal)
    if vy:
        plane, normal = ((bounds.top - radius, (0.0, -1.0)) if vy > 0
                         else (bounds.bottom + radius, (0.0, 1.0)))
        time = (plane - y) / vy
        if bounds.left - EPSILON <= x + vx * time <= bounds.right + EPSILON:
            add(time, normal)

    speed_squared = vx * vx + vy * vy
    if speed_squared:
        for cx, cy, sx, sy in (
            (bounds.left, bounds.top, -1, -1),
            (bounds.right, bounds.top, 1, -1),
            (bounds.left, bounds.bottom, -1, 1),
            (bounds.right, bounds.bottom, 1, 1),
        ):
            dx, dy = x - cx, y - cy
            projection = dx * vx + dy * vy
            discriminant = projection * projection - speed_squared * (
                dx * dx + dy * dy - radius * radius
            )
            if discriminant < -EPSILON:
                continue
            time = (-projection - sqrt(max(0.0, discriminant))) / speed_squared
            hit_x, hit_y = x + vx * time, y + vy * time
            if (sx * (hit_x - cx) >= -EPSILON
                    and sy * (hit_y - cy) >= -EPSILON):
                length = hypot(hit_x - cx, hit_y - cy)
                if length > EPSILON:
                    add(time, ((hit_x - cx) / length, (hit_y - cy) / length))
    return min(contacts, key=lambda contact: contact.time) if contacts else None
