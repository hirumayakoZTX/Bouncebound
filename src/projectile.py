"""Bounded fixed-step orb simulation and immutable physics events."""

from collections.abc import Callable
from dataclasses import dataclass, field
from math import atan2, cos, hypot, isfinite, pi, radians, sin

from src.collision import (
    Bounds, Contact, EPSILON, Point, Target, circle_overlaps, is_approaching, sweep_circle,
)
from src.constants import (
    BATTLEFIELD_ORIGIN, BATTLEFIELD_SIZE, MAX_PHYSICS_STEPS, MAX_STEP_CONTACTS,
    MAX_BP, ORB_DAMAGE, ORB_MAX_HITS, ORB_MAX_LIFETIME, ORB_RADIUS, ORB_SPEED, PHYSICS_STEP,
)


ARENA = Bounds(*BATTLEFIELD_ORIGIN,
               BATTLEFIELD_ORIGIN[0] + BATTLEFIELD_SIZE[0],
               BATTLEFIELD_ORIGIN[1] + BATTLEFIELD_SIZE[1])


@dataclass(frozen=True)
class HitEvent:
    projectile_id: int
    target_id: int
    damage: int
    position: Point
    normal: Point


TargetProvider = Callable[[], tuple[Target, ...]]
HitHandler = Callable[[HitEvent], None]


def _ordered_targets(targets: tuple[Target, ...]) -> tuple[Target, ...]:
    if len({target.target_id for target in targets}) != len(targets):
        raise ValueError("Collision targets must have unique stable IDs")
    return tuple(sorted(targets, key=lambda target: target.target_id))


def firing_velocities(origin: Point, target: Point, bp: int) -> tuple[Point, ...]:
    """Center a symmetric fan; compress steep fans to keep all rays leftward."""
    if type(bp) is not int or not 1 <= bp <= MAX_BP:
        raise ValueError("BP must be an integer from 1 to 5")
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    if dx >= 0 or not isfinite(hypot(dx, dy)):
        raise ValueError("A shot requires a finite target left of its origin")
    heading = atan2(dy, -dx)
    spread = radians(2.5 * (bp - 1))
    # Reserve half the angular room to vertical so outer rays can enter naturally.
    available = (pi / 2 - abs(heading)) / 2
    scale = min(1.0, available / spread) if spread else 1.0
    offsets = [radians(5 * (index - (bp - 1) / 2)) * scale for index in range(bp)]
    return tuple((-ORB_SPEED * cos(heading + offset), ORB_SPEED * sin(heading + offset))
                 for offset in offsets)


@dataclass(frozen=True)
class ProjectileSnapshot:
    projectile_id: int
    position: Point
    velocity: Point
    radius: float
    age: float
    hits: int
    active: bool
    entered_arena: bool


@dataclass
class Projectile:
    projectile_id: int
    position: Point
    velocity: Point
    radius: float = ORB_RADIUS
    damage: int = ORB_DAMAGE
    max_hits: int = ORB_MAX_HITS
    max_lifetime: float = ORB_MAX_LIFETIME
    arena: Bounds = ARENA
    age: float = field(default=0.0, init=False)
    hits: int = field(default=0, init=False)
    active: bool = field(default=True, init=False)
    entered_arena: bool = field(default=False, init=False)
    contact_ids: set[int] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        if (not all(isfinite(v) for v in (*self.position, *self.velocity, self.radius,
                                          self.max_lifetime))
                or self.radius <= 0 or self.max_lifetime <= 0 or self.max_hits < 1):
            raise ValueError("Projectile geometry and limits must be finite and positive")
        self.position = tuple(self.position)
        self.velocity = tuple(self.velocity)
        self.entered_arena = self.arena.inset(self.radius).contains(self.position)

    @classmethod
    def launch(cls, projectile_id: int, origin: Point, target: Point) -> "Projectile":
        dx, dy = target[0] - origin[0], target[1] - origin[1]
        length = hypot(dx, dy)
        if not isfinite(length) or length <= EPSILON or dx >= 0:
            raise ValueError("A projectile requires a finite target left of its origin")
        return cls(projectile_id, origin, (ORB_SPEED * dx / length, ORB_SPEED * dy / length))

    def snapshot(self) -> ProjectileSnapshot:
        return ProjectileSnapshot(self.projectile_id, self.position, self.velocity,
                                  self.radius, self.age, self.hits, self.active,
                                  self.entered_arena)

    def _clear_separated_contacts(self, targets: tuple[Target, ...]) -> None:
        self.contact_ids.intersection_update(
            target.target_id for target in targets
            if circle_overlaps(self.position, self.radius, target.bounds)
        )

    def _wall_contacts(self, duration: float, inner: Bounds) -> list[Contact]:
        x, y = self.position
        vx, vy = self.velocity
        contacts = []
        planes = []
        if vx < 0:
            planes.append(((inner.left - x) / vx, (1.0, 0.0)))
        elif vx > 0 and self.entered_arena:
            planes.append(((inner.right - x) / vx, (-1.0, 0.0)))
        if vy < 0:
            planes.append(((inner.top - y) / vy, (0.0, 1.0)))
        elif vy > 0:
            planes.append(((inner.bottom - y) / vy, (0.0, -1.0)))
        for time, normal in planes:
            if -EPSILON <= time <= duration + EPSILON:
                time = min(duration, max(0.0, time))
                contacts.append(Contact(time, normal, (x + vx * time, y + vy * time)))
        return contacts

    def _reflect(self, normal: Point) -> None:
        vx, vy = self.velocity
        nx, ny = normal
        dot = vx * nx + vy * ny
        if dot < 0:
            self.velocity = (vx - 2 * dot * nx, vy - 2 * dot * ny)

    def step(
        self, dt: float, targets: tuple[Target, ...] = (), *,
        target_provider: TargetProvider | None = None, on_hit: HitHandler | None = None,
    ) -> tuple[HitEvent, ...]:
        """Advance a step using swept impacts; inactive orbs are never touched.

        Top/bottom planes extend across the entry gap. The right wall is enabled
        only once the entire circle enters. Simultaneous wall normals both apply;
        equal-time target ties use stable IDs. A contact-iteration safety cap
        consumes leftover step time without motion in pathological target layouts.
        Optional generic hooks resolve a contact before later targets are checked.
        """
        if not self.active:
            return ()
        if not isfinite(dt) or dt < 0:
            raise ValueError("Simulation time must be finite and nonnegative")
        if dt == 0:
            return ()
        inner = self.arena.inset(self.radius)
        if self.entered_arena and not inner.contains(self.position):
            self.active = False
            return ()
        duration = min(dt, max(0.0, self.max_lifetime - self.age))
        remaining = duration
        events = []
        ordered = _ordered_targets(targets)
        for _ in range(MAX_STEP_CONTACTS):
            if remaining <= EPSILON or not self.active:
                break
            if inner.contains(self.position):
                self.entered_arena = True
            if target_provider is not None:
                ordered = _ordered_targets(target_provider())
            self._clear_separated_contacts(ordered)
            walls = self._wall_contacts(remaining, inner)
            impacts = []
            for target in ordered:
                if target.target_id not in self.contact_ids:
                    contact = sweep_circle(self.position, self.velocity, self.radius,
                                           target.bounds, remaining)
                    if contact is not None:
                        impacts.append((contact, target))
            candidates = [contact.time for contact in walls]
            candidates.extend(contact.time for contact, _ in impacts)
            # Crossing this plane is an entry event, not a reflection.
            entry_time = None
            if not self.entered_arena and self.velocity[0] < 0:
                time = (inner.right - self.position[0]) / self.velocity[0]
                if 0 <= time <= remaining:
                    entry_time = time
                    candidates.append(time)
            if not candidates:
                self.position = (self.position[0] + self.velocity[0] * remaining,
                                 self.position[1] + self.velocity[1] * remaining)
                remaining = 0.0
                break
            elapsed = min(candidates)
            self.position = (self.position[0] + self.velocity[0] * elapsed,
                             self.position[1] + self.velocity[1] * elapsed)
            remaining = max(0.0, remaining - elapsed)
            if entry_time is not None and abs(entry_time - elapsed) <= EPSILON:
                self.entered_arena = True
            for contact in walls:
                if abs(contact.time - elapsed) <= EPSILON:
                    self._reflect(contact.normal)
            for contact, target in impacts:
                if abs(contact.time - elapsed) > EPSILON:
                    continue
                if target_provider is not None:
                    available = {item.target_id for item in target_provider()}
                    if target.target_id not in available:
                        continue
                self.position = contact.position
                if target.reflects and is_approaching(self.velocity, contact.normal):
                    self._reflect(contact.normal)
                self.contact_ids.add(target.target_id)
                # Pre-existing penetration is corrected and tracked, never scored as a hit.
                if not contact.is_impact:
                    continue
                if target.reflects:
                    self.hits += 1
                event = HitEvent(self.projectile_id, target.target_id,
                                 self.damage if target.reflects else 0,
                                 self.position, contact.normal)
                events.append(event)
                if on_hit is not None:
                    on_hit(event)
                if self.hits >= self.max_hits:
                    self.active = False
                    break
        self.age += duration if self.active else duration - remaining
        if self.age >= self.max_lifetime - EPSILON:
            self.age = self.max_lifetime
            self.active = False
        if inner.contains(self.position):
            self.entered_arena = True
        if self.entered_arena and not inner.contains(self.position):
            self.active = False
        if target_provider is not None:
            ordered = _ordered_targets(target_provider())
        self._clear_separated_contacts(ordered)
        return tuple(events)


@dataclass
class FixedStepPhysics:
    accumulator: float = 0.0

    def advance(
        self, dt: float, projectiles: list[Projectile], targets: tuple[Target, ...] = (), *,
        target_provider: TargetProvider | None = None, on_hit: HitHandler | None = None,
    ) -> tuple[HitEvent, ...]:
        """Accept at most 0.25 seconds per frame; drop excess time, never backlog it.

        Projectiles use stable ID order within each step. Inline hit callbacks and
        fresh target queries prevent removed targets responding to later contacts.
        """
        if not isfinite(dt) or dt < 0:
            raise ValueError("Frame time must be finite and nonnegative")
        if not any(projectile.active for projectile in projectiles):
            self.accumulator = 0.0
            return ()
        targets = _ordered_targets(targets)
        self.accumulator += min(dt, PHYSICS_STEP * MAX_PHYSICS_STEPS)
        steps = min(MAX_PHYSICS_STEPS, int((self.accumulator + EPSILON) / PHYSICS_STEP))
        events = []
        for _ in range(steps):
            for projectile in sorted(projectiles, key=lambda orb: orb.projectile_id):
                events.extend(projectile.step(PHYSICS_STEP, targets,
                                               target_provider=target_provider, on_hit=on_hit))
            self.accumulator = max(0.0, self.accumulator - PHYSICS_STEP)
            if not any(projectile.active for projectile in projectiles):
                self.accumulator = 0.0
                break
        return tuple(events)
