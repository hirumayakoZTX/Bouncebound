"""Run data and validated scene transitions without rendering dependencies."""

from dataclasses import dataclass, replace
from collections.abc import Mapping
from types import MappingProxyType
from math import isfinite

from src.constants import (
    AIM_ORIGIN_OFFSET, BATTLEFIELD_ORIGIN, BATTLEFIELD_SIZE,
    GRID_ROWS, INITIAL_PLAYER_ROW, PLAYER_X, TILE_SIZE,
)
from src.states import ACTIVE_STATES, GameOverReason, GameState
from src.collision import Target
from src.projectile import FixedStepPhysics, HitEvent, Projectile, ProjectileSnapshot
from src.projectile import firing_velocities
from src.combat import Combat
from src.demo import create_demo_combat
from src.encounter import Encounter, EncounterDefinition, EncounterOutcome
from src.entities import (
    Crystal, CrystalSnapshot, Enemy, EnemySnapshot, EnemyTurnContext, validate_damage,
)
from src.turns import resolve_enemy_phase
from src.stage_config import load_stage, validate_stage_registry
from src.spells import (
    SpellContext, SpellEngine, SpellFailure, SpellId, SpellResult, StatusCheck, get_spell,
)
from src.offensive_spells import OFFENSIVE_DAMAGE, OffensiveSpellResult, execute_offensive
from src.statuses import StatusEffect, StatusEvent, StatusEventKind, StatusKind, StatusState
from src.hazards import HazardState, PoisonTile
from src.status_runtime import process_status_phase
from src.support_spells import SupportSpellResult, execute_support
from src.player_actions import (
    ActionKind, MainAction, SpellHUD, SPELL_ANIMATION_SECONDS, spell_failure_message,
)


STAGE_ONE = load_stage("stage_01.json")
STAGE_TWO = load_stage("stage_02.json")


# Action eligibility is checked by the controller before requesting scene edges.
_ACTION_END_STATES = frozenset({
    GameState.TURN_RESOLVE,
    GameState.STAGE_CLEAR,
    GameState.VICTORY,
    GameState.GAME_OVER,
})
_TRANSITIONS = {
    GameState.MENU: frozenset({GameState.STAGE_INTRO}),
    GameState.STAGE_INTRO: frozenset({GameState.PLAYER_AIM}),
    GameState.PLAYER_AIM: frozenset({
        GameState.SHOT_ANIMATION, GameState.SPELL_ANIMATION, GameState.GAME_OVER,
    }),
    GameState.SHOT_ANIMATION: _ACTION_END_STATES,
    GameState.SPELL_ANIMATION: _ACTION_END_STATES,
    GameState.TURN_RESOLVE: frozenset({
        GameState.PLAYER_AIM, GameState.STAGE_CLEAR,
        GameState.VICTORY, GameState.GAME_OVER,
    }),
    GameState.STAGE_CLEAR: frozenset({GameState.STAGE_INTRO}),
    GameState.VICTORY: frozenset({GameState.RESULTS}),
    GameState.GAME_OVER: frozenset(),
    GameState.RESULTS: frozenset(),
}


@dataclass(frozen=True)
class WorldSnapshot:
    state: GameState
    stage: int
    turn_index: int
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    bp: int
    player_row: int
    player_position: tuple[int, int]
    aim_origin: tuple[int, int]
    aim_target: tuple[float, float] | None
    paused_state: GameState | None
    projectiles: tuple[ProjectileSnapshot, ...]
    enemies: tuple[EnemySnapshot, ...]
    crystals: tuple[CrystalSnapshot, ...]
    pending_bp: int
    last_resolved_turn: int | None
    game_over_reason: GameOverReason | None
    spawned_waves: int
    total_waves: int
    statuses: tuple[StatusEffect, ...] = ()
    reraise_used: bool = False
    hazards: tuple[PoisonTile, ...] = ()
    status_events: tuple[StatusEvent, ...] = ()
    selected_spell: SpellId | None = None
    spell_hud: SpellHUD | None = None
    spell_feedback: str = ""
    pending_action: MainAction | None = None
    spell_remaining: float = 0.0
    spell_result: OffensiveSpellResult | SupportSpellResult | None = None
    next_stage_available: bool = False
    has_boss_wave: bool = False
    boss_wave_spawned: bool = False
    bosses_remaining: int = 0
    boss_total: int = 0


class World:
    def __init__(self, *, demo: bool | None = None,
                 encounter: EncounterDefinition | None = None,
                 stages: Mapping[int, EncounterDefinition] | None = None) -> None:
        # Explicit demo modes retain the small regression fixtures used by earlier systems.
        if demo is not None and (type(demo) is not bool or encounter is not None):
            raise ValueError("Choose either a demo fixture or an encounter definition")
        if encounter is not None and not isinstance(encounter, EncounterDefinition):
            raise ValueError("Encounter configuration must be an EncounterDefinition")
        if stages is not None and (demo is not None or encounter is not None):
            raise ValueError("Choose a stage registry, a single encounter, or a demo fixture")
        definitions = (stages if stages is not None else {1: encounter} if encounter is not None
                       else {1: STAGE_ONE, 2: STAGE_TWO})
        self._stage_definitions = validate_stage_registry(definitions)
        self._demo = demo
        self._encounter_definition = self._stage_definitions[1] if demo is None else None
        self.reset()

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def paused_state(self) -> GameState | None:
        return self._paused_state

    @property
    def enemies(self) -> dict[int, Enemy]:
        return self.combat.enemies

    @property
    def crystals(self) -> dict[int, Crystal]:
        return self.combat.crystals

    @property
    def pending_bp(self) -> int:
        return self.combat.pending_bp

    @property
    def player_position(self) -> tuple[int, int]:
        return (PLAYER_X, BATTLEFIELD_ORIGIN[1] + TILE_SIZE // 2
                + TILE_SIZE * self.player_row)

    @property
    def aim_origin(self) -> tuple[int, int]:
        x, y = self.player_position
        return (x - AIM_ORIGIN_OFFSET, y)

    def reset(self) -> None:
        """Restore the menu and all data currently owned by the run."""
        self.stage = 1
        self.turn_index = 1
        self.hp = self.max_hp = 100
        self.mp = self.max_mp = 100
        self.spells = SpellEngine()
        self.statuses = StatusState()
        self.hazards = HazardState()
        self.reraise_used = False
        self.bp = 1
        self.player_row = INITIAL_PLAYER_ROW
        self.aim_target: tuple[float, float] | None = None
        self._state = GameState.MENU
        self._paused_state: GameState | None = None
        self.projectiles: list[Projectile] = []
        self._physics = FixedStepPhysics()
        self._next_projectile_id = 1
        self.combat = create_demo_combat() if self._demo else Combat()
        self.encounter = (Encounter(self._encounter_definition)
                          if self._encounter_definition is not None else None)
        self._pending_action: MainAction | None = None
        self._next_action_id = 1
        self.selected_spell: SpellId | None = None
        self.spell_feedback = ""
        self._spell_remaining = 0.0
        self.last_spell_result: OffensiveSpellResult | SupportSpellResult | None = None
        self.last_resolved_turn: int | None = None
        self.game_over_reason: GameOverReason | None = None
        self._cleared_stage: int | None = None

    @property
    def _pending_turn(self) -> int | None:
        """Compatibility view of the single pending action's turn."""
        return self._pending_action.turn if self._pending_action else None

    def _can_act(self) -> bool:
        return (self.state is GameState.PLAYER_AIM and self.hp > 0
                and self._pending_action is None and not self.projectiles)

    def _action_id(self) -> tuple[str, int]:
        sequence = self._next_action_id
        while self.spells.has_committed_action(f"player-action:{sequence}"):
            sequence += 1
        return f"player-action:{sequence}", sequence

    def select_spell(self, spell_id: SpellId | str) -> bool:
        if not self._can_act():
            return False
        definition = get_spell(spell_id)
        failure = (SpellFailure.INVALID_SPELL if definition is None else
                   SpellFailure.STAGE_LOCKED if self.stage < definition.unlock_stage else None)
        if failure is not None:
            self.spell_feedback = spell_failure_message(failure)
            return False
        self.selected_spell = definition.spell_id
        self.spell_feedback = f"Spell selected: {definition.name}"
        return True

    def cast_selected_spell(self) -> SpellResult:
        """Execute once, then claim the same main-action lifecycle used by shots."""
        if not self._can_act():
            return SpellResult(failure=SpellFailure.INVALID_STATE)
        if self.selected_spell is None:
            self.spell_feedback = spell_failure_message(SpellFailure.NO_SELECTION)
            return SpellResult(failure=SpellFailure.NO_SELECTION)
        action_id, sequence = self._action_id()
        executor = (self.execute_offensive_spell if self.selected_spell in OFFENSIVE_DAMAGE
                    else self.execute_support_spell)
        result = executor(action_id, self.selected_spell)
        if not result.valid:
            self.spell_feedback = spell_failure_message(result.failure)
            return result.commit
        self._pending_action = MainAction(action_id, ActionKind.SPELL, self.turn_index)
        self._next_action_id = sequence + 1
        self.last_spell_result = result
        self._spell_remaining = SPELL_ANIMATION_SECONDS
        self.spell_feedback = f"Cast: {get_spell(result.cast.spell_id).name}"
        self.transition_to(GameState.SPELL_ANIMATION)
        return result.commit

    @property
    def stage_definitions(self) -> Mapping[int, EncounterDefinition]:
        return MappingProxyType(self._stage_definitions.copy())

    @property
    def can_advance_stage(self) -> bool:
        return (self.state is GameState.STAGE_CLEAR and self._cleared_stage == self.stage
                and self.encounter is not None and not self.encounter.definition.final
                and self.stage + 1 in self._stage_definitions
                and self._pending_action is None and not self.projectiles)

    def advance_stage(self) -> bool:
        """Enter a registered next encounter after an authorized clear.

        Each stage starts a fresh encounter clock and clears cooldowns, effects,
        Reraise allowance, histories, and identifiers along with HP/MP/BP reset.
        The default application registers only the complete Stage 1.
        """
        if not self.can_advance_stage:
            return False
        definition = self._stage_definitions[self.stage + 1]
        self.reset()
        self.stage = definition.stage
        self.encounter = Encounter(definition)
        return self.transition_to(GameState.STAGE_INTRO)

    def start_new_run(self) -> None:
        self.reset()
        self.transition_to(GameState.STAGE_INTRO)

    def restart(self) -> bool:
        if self.state not in (GameState.GAME_OVER, GameState.STAGE_CLEAR,
                              GameState.VICTORY, GameState.RESULTS):
            return False
        self.start_new_run()
        return True

    def transition_to(self, target: GameState) -> bool:
        """Reject invalid edges without changing scene, pause data, or resources.

        Phase edges alone never authorize actions. Stage-end edges additionally
        require a completion claim issued by the canonical turn resolver.
        """
        if not isinstance(target, GameState):
            return False
        if self.state is GameState.STAGE_CLEAR and target is GameState.STAGE_INTRO:
            return self.advance_stage()
        if target in (GameState.STAGE_CLEAR, GameState.VICTORY):
            if self._cleared_stage != self.stage or self.encounter is None:
                return False
            expected = GameState.VICTORY if self.encounter.definition.final else GameState.STAGE_CLEAR
            if target is not expected:
                return False
        if target is GameState.RESULTS and self._cleared_stage != self.stage:
            return False
        if self.state is GameState.PAUSED:
            if target is not self.paused_state:
                return False
            self._paused_state = None
        elif target is GameState.PAUSED:
            if self.state not in ACTIVE_STATES:
                return False
            self._paused_state = self.state
        elif target not in _TRANSITIONS[self.state]:
            return False

        previous_state = self.state
        self._state = target
        if previous_state is GameState.STAGE_INTRO and target is GameState.PLAYER_AIM:
            self.spawn_waves()
        return True

    def spawn_waves(self) -> tuple[int, ...]:
        """Spawn only between actions; scheduled entries retry at later boundaries."""
        if (self.encounter is None
                or self.state not in (GameState.PLAYER_AIM, GameState.TURN_RESOLVE)
                or self._pending_action is not None
                or any(orb.active for orb in self.projectiles)):
            return ()
        return self.encounter.spawn_due(self.turn_index, self.combat)

    def pause(self) -> bool:
        return self.transition_to(GameState.PAUSED)

    def resume(self) -> bool:
        if self.paused_state is None:
            return False
        return self.transition_to(self.paused_state)

    def move_player(self, delta_row: int) -> bool:
        """Move a single row during aiming without spending a turn or resources."""
        if (self.state is not GameState.PLAYER_AIM
                or type(delta_row) is not int or delta_row not in (-1, 1)
                or self.statuses.is_active(StatusKind.BIND, self.turn_index)):
            return False
        next_row = self.player_row + delta_row
        if not 0 <= next_row < GRID_ROWS:
            return False
        self.player_row = next_row
        return True

    def set_aim_target(self, target: tuple[float, float]) -> bool:
        """Accept a finite battlefield point; invalid active input clears aiming."""
        if self.state is not GameState.PLAYER_AIM:
            return False
        if (not isinstance(target, tuple) or len(target) != 2
                or any(type(value) not in (int, float) or not isfinite(value)
                       for value in target)):
            self.aim_target = None
            return False

        x, y = target
        left, top = BATTLEFIELD_ORIGIN
        width, height = BATTLEFIELD_SIZE
        # The design's field bounds include the right and bottom edges.
        if (left <= x <= left + width and top <= y <= top + height
                and x < self.aim_origin[0]):
            self.aim_target = (float(x), float(y))
            return True
        self.aim_target = None
        return False

    def fire(self) -> bool:
        """Capture current BP and launch its complete, independent orb fan."""
        if not self._can_act() or self.aim_target is None:
            return False
        if not self.set_aim_target(self.aim_target):
            return False
        velocities = firing_velocities(self.aim_origin, self.aim_target, self.bp)
        self.projectiles = [Projectile(self._next_projectile_id + index, self.aim_origin, velocity)
                            for index, velocity in enumerate(velocities)]
        self._next_projectile_id += len(velocities)
        self._physics.accumulator = 0.0
        action_id, sequence = self._action_id()
        self._pending_action = MainAction(action_id, ActionKind.SHOT, self.turn_index)
        self._next_action_id = sequence + 1
        self.spell_feedback = ""
        self.last_spell_result = None
        return self.transition_to(GameState.SHOT_ANIMATION)

    def advance_time(
        self, dt: float, targets: tuple[Target, ...] = ()
    ) -> tuple[HitEvent, ...]:
        """Resolve each impact synchronously; returned events are already applied."""
        action = self._pending_action
        if action is None or action.completed or action.turn != self.turn_index:
            return ()
        if self.state is GameState.SPELL_ANIMATION and action.kind is ActionKind.SPELL:
            if type(dt) not in (int, float) or not isfinite(dt) or dt < 0:
                raise ValueError("Elapsed time must be finite and nonnegative")
            self._spell_remaining = max(0.0, self._spell_remaining - dt)
            if self._spell_remaining <= 1e-9:
                self._spell_remaining = 0.0
                self._pending_action = replace(action, completed=True)
                self.transition_to(GameState.TURN_RESOLVE)
            return ()
        if self.state is not GameState.SHOT_ANIMATION or action.kind is not ActionKind.SHOT:
            return ()
        events = self._physics.advance(
            dt, self.projectiles,
            target_provider=lambda: self.combat.targets() + targets,
            on_hit=self.combat.handle_hit,
        )
        self.projectiles = [orb for orb in self.projectiles if orb.active]
        if not self.projectiles:
            self.bp = self.combat.finish_shot(self.bp)
            self._pending_action = replace(action, completed=True)
            self.transition_to(GameState.TURN_RESOLVE)
        return events

    def spell_context(self) -> SpellContext:
        """Read-only adapter for current targets, resources, and action ownership."""
        return SpellContext(
            state=self.state, stage=self.stage, turn_index=self.turn_index,
            hp=self.hp, max_hp=self.max_hp, mp=self.mp,
            player_row=self.player_row, player_position=self.player_position,
            enemies=tuple(enemy.snapshot() for enemy in sorted(
                self.enemies.values(), key=lambda enemy: enemy.enemy_id) if enemy.active),
            action_pending=bool(self.projectiles) or self._pending_action is not None,
            statuses=self.statuses.snapshot(), reraise_used=self.reraise_used,
        )

    def validate_spell(self, spell_id: SpellId | str, *,
                       status_check: StatusCheck | None = None) -> SpellResult:
        return self.spells.validate(spell_id, self.spell_context(), status_check=status_check)

    def commit_spell(self, action_id: str, spell_id: SpellId | str, *,
                     status_check: StatusCheck | None = None) -> SpellResult:
        """Model-only payment; future casting integration must resolve actual effects."""
        return self.spells.commit(action_id, spell_id, self, status_check=status_check)

    def execute_offensive_spell(self, action_id: str, spell_id: SpellId | str, *,
                                status_check: StatusCheck | None = None) -> OffensiveSpellResult:
        """Low-level commit/effects; player input uses cast_selected_spell."""
        return execute_offensive(action_id, spell_id, self, self.spells, self.combat,
                                 status_check=status_check)

    def execute_support_spell(self, action_id: str, spell_id: SpellId | str, *,
                              status_check: StatusCheck | None = None) -> SupportSpellResult:
        """Model-only healing, cleansing, or grants; no status/turn processing."""
        return execute_support(action_id, spell_id, self, self.spells, status_check=status_check)

    @property
    def status_events(self) -> tuple[StatusEvent, ...]:
        return self.statuses.events

    def apply_status(self, kind: StatusKind, duration: int | None = None, *,
                     source_id: int | str | None = None) -> StatusEvent:
        """Direct model placement for fixtures and future abilities; no spell payment."""
        defaults = {StatusKind.POISON: 3, StatusKind.BIND: 1, StatusKind.DOOM: 5,
                    StatusKind.WARD: 1, StatusKind.LEVITATION: 1, StatusKind.RERAISE: None}
        if not isinstance(kind, StatusKind):
            raise ValueError("Status kind must be a StatusKind")
        effect = StatusEffect(kind, defaults[kind] if duration is None else duration,
                              self.turn_index, source_id,
                              charges=1 if kind in (StatusKind.WARD, StatusKind.RERAISE) else None)
        self.statuses.put(effect)
        return self.status_events[-1]

    def place_poison_tile(self, row: int, duration: int = 2, *,
                          source_id: int | str | None = None) -> StatusEvent:
        event = self.hazards.put(PoisonTile(row, duration, self.turn_index, source_id))
        self.statuses.record(event)
        return event

    def remove_poison_tile(self, row: int) -> PoisonTile | None:
        tile = self.hazards.remove(row)
        if tile is not None:
            self.statuses.record(StatusEvent(StatusEventKind.HAZARD_REMOVED, self.turn_index,
                                              row=row, source_id=tile.source_id))
        return tile

    def apply_player_damage(self, amount: int, *, source: str = "direct",
                            row: int | None = None) -> int:
        """Return actual HP lost before any revival; Ward covers ordinary damage."""
        validate_damage(amount)
        return self._resolve_player_damage(amount, source=source, row=row, forced=False)

    def force_player_knockout(self, *, source: str = "doom") -> int:
        """Forced knockout bypasses Ward, while still allowing one Reraise."""
        return self._resolve_player_damage(0, source=source, row=None, forced=True)

    def _resolve_player_damage(self, amount: int, *, source: str,
                               row: int | None, forced: bool) -> int:
        if self.state not in ACTIVE_STATES or self.hp <= 0 or (not forced and amount == 0):
            return 0
        before = self.hp
        if not forced and self.statuses.is_active(StatusKind.WARD, self.turn_index):
            self.statuses.record(StatusEvent(StatusEventKind.WARD_BLOCKED, self.turn_index,
                                              StatusKind.WARD, row=row, source_id=source,
                                              attempted_damage=amount, hp_before=before, hp_after=before))
            self.statuses.remove(StatusKind.WARD, turn=self.turn_index)
            return 0
        self.hp = 0 if forced else max(0, before - amount)
        lost = before - self.hp
        kind = (StatusEventKind.FORCED_KNOCKOUT if forced else
                StatusEventKind.POISON_DAMAGE if source == "poison" else
                StatusEventKind.HAZARD_DAMAGE if source == "poison_tile" else StatusEventKind.DAMAGE)
        self.statuses.record(StatusEvent(kind, self.turn_index, row=row, source_id=source,
                                          amount=lost, attempted_damage=before if forced else amount,
                                          hp_before=before, hp_after=self.hp))
        if self.hp == 0:
            revival = self.statuses.get(StatusKind.RERAISE)
            if revival is not None and self.statuses.is_active(StatusKind.RERAISE, self.turn_index):
                self.statuses.remove(StatusKind.RERAISE, turn=self.turn_index)
                self.hp = revival.revival_hp
                self.statuses.record(StatusEvent(StatusEventKind.RERAISE_ACTIVATED, self.turn_index,
                                                  StatusKind.RERAISE, source_id=revival.source_id,
                                                  amount=self.hp, hp_before=0, hp_after=self.hp))
            else:
                self._end_run(GameOverReason.HP_DEPLETED)
        return lost

    def _end_run(self, reason: GameOverReason) -> None:
        self._pending_action = None
        self._spell_remaining = 0.0
        self.game_over_reason = reason
        self.transition_to(GameState.GAME_OVER)

    def check_stage_end(self) -> bool:
        """A stage clears only after the final action and all required defeats."""
        return (self.state is GameState.TURN_RESOLVE
                and not any(orb.active for orb in self.projectiles)
                and not self.combat.pending_deaths and self.pending_bp == 0
                and self.encounter is not None and self.stage == self.encounter.definition.stage
                and self.encounter.outcome(self.combat) is EncounterOutcome.CLEARED)

    def resolve_turn(self) -> bool:
        """Resolve one completed main action exactly once, without a draw call."""
        if (self.state is not GameState.TURN_RESOLVE
                or self._pending_action is None
                or not self._pending_action.completed
                or self._pending_turn != self.turn_index
                or any(orb.active for orb in self.projectiles)):
            return False
        if self.hp <= 0:
            self._end_run(GameOverReason.HP_DEPLETED)
            return True
        self.bp = self.combat.finish_shot(self.bp)
        # Claim the action before invoking hooks, preventing repeated/reentrant phases.
        self._pending_action = None
        if self.check_stage_end():
            self._cleared_stage = self.stage
            self.transition_to(GameState.VICTORY if self.encounter.definition.final
                               else GameState.STAGE_CLEAR)
            return True
        initial_statuses = self.statuses.snapshot()
        initial_hazards = self.hazards.snapshot()
        context = EnemyTurnContext(
            turn_index=self.turn_index,
            damage_player=lambda amount: self.apply_player_damage(amount, source="enemy_contact"),
            attack_player=lambda amount: self.apply_player_damage(amount, source="boss_attack"),
            player_defeated=lambda: self.hp <= 0 or self.state is GameState.GAME_OVER,
            player_row=self.player_row,
            ability_player=lambda amount: self.apply_player_damage(amount, source="enemy_ability"),
            apply_status=lambda kind, duration, source: self.apply_status(
                kind, duration, source_id=source),
            place_poison_tile=lambda row, duration, source: self.place_poison_tile(
                row, duration, source_id=source),
        )
        resolve_enemy_phase(self.enemies.values(), context)
        process_status_phase(self, initial_statuses, initial_hazards)
        self.last_resolved_turn = self.turn_index
        if self.hp <= 0 or self.state is GameState.GAME_OVER:
            if self.state is not GameState.GAME_OVER:
                self._end_run(GameOverReason.HP_DEPLETED)
        elif (self.encounter is not None
              and self.encounter.outcome(self.combat) is EncounterOutcome.FAILED):
            self._end_run(GameOverReason.DEFENSE_FAILED)
        else:
            self.turn_index += 1
            self.spell_feedback = ""
            self.last_spell_result = None
            self.spawn_waves()
            self.transition_to(GameState.PLAYER_AIM)
        return True

    def snapshot(self) -> WorldSnapshot:
        definition = get_spell(self.selected_spell) if self.selected_spell is not None else None
        hud = (SpellHUD(definition, self.spells.next_ready_turn(self.selected_spell),
                        self.validate_spell(self.selected_spell).failure)
               if definition is not None else None)
        return WorldSnapshot(
            state=self.state,
            stage=self.stage,
            turn_index=self.turn_index,
            hp=self.hp,
            max_hp=self.max_hp,
            mp=self.mp,
            max_mp=self.max_mp,
            bp=self.bp,
            player_row=self.player_row,
            player_position=self.player_position,
            aim_origin=self.aim_origin,
            aim_target=self.aim_target,
            paused_state=self.paused_state,
            projectiles=tuple(orb.snapshot() for orb in self.projectiles if orb.active),
            enemies=tuple(enemy.snapshot() for enemy in sorted(
                self.enemies.values(), key=lambda enemy: enemy.enemy_id
            ) if enemy.active),
            crystals=tuple(crystal.snapshot() for crystal in sorted(
                self.crystals.values(), key=lambda crystal: crystal.crystal_id
            ) if not crystal.collected),
            pending_bp=self.pending_bp,
            last_resolved_turn=self.last_resolved_turn,
            game_over_reason=self.game_over_reason,
            spawned_waves=len(self.encounter.spawned_waves) if self.encounter else 0,
            total_waves=len(self.encounter.definition.waves) if self.encounter else 0,
            statuses=self.statuses.snapshot(),
            reraise_used=self.reraise_used,
            hazards=self.hazards.snapshot(),
            status_events=self.status_events,
            selected_spell=self.selected_spell,
            spell_hud=hud,
            spell_feedback=self.spell_feedback,
            pending_action=self._pending_action,
            spell_remaining=self._spell_remaining,
            spell_result=self.last_spell_result,
            next_stage_available=self.can_advance_stage,
            has_boss_wave=self.encounter is not None and self.encounter.definition.boss_wave is not None,
            boss_wave_spawned=self.encounter.boss_wave_spawned if self.encounter else False,
            bosses_remaining=sum(enemy.active and enemy.is_boss for enemy in self.enemies.values()),
            boss_total=(len(self.encounter.definition.boss_wave.spawns)
                        if self.encounter and self.encounter.definition.boss_wave else 0),
        )
