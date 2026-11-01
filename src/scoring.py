"""Authoritative, attempt-scoped scoring without presentation dependencies."""

from dataclasses import dataclass, field, replace

CHAIN_BONUS = 50
COMBO_BONUS = 100
FULL_HP_BONUS = 1500
FULL_MP_BONUS = 3000
NO_DAMAGE_BONUS = 20000


@dataclass(frozen=True)
class ScoreBreakdown:
    defeats: int = 0
    chains: int = 0
    combos: int = 0
    stage_bonuses: int = 0

    @property
    def total(self) -> int:
        return self.defeats + self.chains + self.combos + self.stage_bonuses

    def plus(self, other: "ScoreBreakdown") -> "ScoreBreakdown":
        return ScoreBreakdown(self.defeats + other.defeats, self.chains + other.chains,
                              self.combos + other.combos, self.stage_bonuses + other.stage_bonuses)


@dataclass(frozen=True)
class ScoreEvent:
    stage: int
    attempt: int
    kind: str
    points: int
    entity_id: int | None = None
    action_id: str | None = None


@dataclass(frozen=True)
class ScoreSnapshot:
    breakdown: ScoreBreakdown = ScoreBreakdown()
    attempt_total: int = 0
    events: tuple[ScoreEvent, ...] = ()

    @property
    def total(self) -> int:
        return self.breakdown.total


@dataclass
class ScoreManager:
    stage: int = 1
    attempt: int = 1
    accepted: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    current: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    accepted_events: tuple[ScoreEvent, ...] = ()
    current_events: list[ScoreEvent] = field(default_factory=list)
    killed_ids: set[int] = field(default_factory=set)
    combo_actions: set[str] = field(default_factory=set)
    took_damage: bool = False
    finalized: bool = False

    def _award(self, category: str, kind: str, points: int, *, entity_id: int | None = None,
               action_id: str | None = None) -> None:
        self.current = replace(self.current, **{category: getattr(self.current, category) + points})
        self.current_events.append(ScoreEvent(self.stage, self.attempt, kind, points,
                                              entity_id, action_id))

    def record_death(self, enemy_id: int, base_points: int, source: str) -> None:
        if self.finalized or enemy_id in self.killed_ids:
            return
        self.killed_ids.add(enemy_id)
        self._award('defeats', 'enemy_defeat', base_points, entity_id=enemy_id)
        if source == 'explosion':
            self._award('chains', 'bomb_chain_kill', CHAIN_BONUS, entity_id=enemy_id)

    def complete_shot(self, action_id: str, target_ids: set[int]) -> None:
        if self.finalized or action_id in self.combo_actions:
            return
        self.combo_actions.add(action_id)
        if len(target_ids) >= 3:
            self._award('combos', 'shooting_combo', COMBO_BONUS, action_id=action_id)

    def record_damage(self, lost: int) -> None:
        if lost > 0 and not self.finalized:
            self.took_damage = True

    def finalize_stage(self, hp: int, max_hp: int, mp: int, max_mp: int) -> None:
        if self.finalized:
            return
        for condition, kind, points in ((hp == max_hp, 'full_hp', FULL_HP_BONUS),
                                        (mp == max_mp, 'full_mp', FULL_MP_BONUS),
                                        (not self.took_damage, 'no_damage', NO_DAMAGE_BONUS)):
            if condition:
                self._award('stage_bonuses', kind, points)
        self.accepted = self.accepted.plus(self.current)
        self.accepted_events += tuple(self.current_events)
        self.current = ScoreBreakdown()
        self.current_events.clear()
        self.finalized = True

    def begin_attempt(self, stage: int) -> None:
        self.stage = stage
        self.attempt += 1
        self.current = ScoreBreakdown()
        self.current_events.clear()
        self.killed_ids.clear()
        self.combo_actions.clear()
        self.took_damage = False
        self.finalized = False

    def snapshot(self) -> ScoreSnapshot:
        return ScoreSnapshot(self.accepted.plus(self.current), self.current.total,
                             self.accepted_events + tuple(self.current_events))
