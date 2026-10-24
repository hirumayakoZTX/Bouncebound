"""Run data and validated scene transitions without rendering dependencies."""

from dataclasses import dataclass
from math import isfinite

from src.constants import (
    AIM_ORIGIN_OFFSET, BATTLEFIELD_ORIGIN, BATTLEFIELD_SIZE,
    GRID_ROWS, INITIAL_PLAYER_ROW, PLAYER_X, TILE_SIZE,
)
from src.states import ACTIVE_STATES, GameState
from src.collision import Target
from src.projectile import FixedStepPhysics, HitEvent, Projectile, ProjectileSnapshot
from src.projectile import firing_velocities
from src.combat import Combat
from src.demo import create_demo_combat
from src.entities import Crystal, CrystalSnapshot, Enemy, EnemySnapshot


# Combat and stage conditions remain the responsibility of future systems.
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
        GameState.SHOT_ANIMATION, GameState.SPELL_ANIMATION,
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


class World:
    def __init__(self, *, demo: bool = True) -> None:
        self._demo = demo
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
        self.bp = 1
        self.player_row = INITIAL_PLAYER_ROW
        self.aim_target: tuple[float, float] | None = None
        self._state = GameState.MENU
        self._paused_state: GameState | None = None
        self.projectiles: list[Projectile] = []
        self._physics = FixedStepPhysics()
        self._next_projectile_id = 1
        self.combat = create_demo_combat() if self._demo else Combat()

    def start_new_run(self) -> None:
        self.reset()
        self.transition_to(GameState.STAGE_INTRO)

    def transition_to(self, target: GameState) -> bool:
        """Reject invalid edges without changing scene, pause data, or resources.

        This validates scene order only. Future systems must validate action and
        stage-end conditions before requesting a transition. No turn advances here.
        """
        if not isinstance(target, GameState):
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

        self._state = target
        return True

    def pause(self) -> bool:
        return self.transition_to(GameState.PAUSED)

    def resume(self) -> bool:
        if self.paused_state is None:
            return False
        return self.transition_to(self.paused_state)

    def move_player(self, delta_row: int) -> bool:
        """Move a single row during aiming without spending a turn or resources."""
        if (self.state is not GameState.PLAYER_AIM
                or type(delta_row) is not int or delta_row not in (-1, 1)):
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
        if (self.state is not GameState.PLAYER_AIM or self.aim_target is None
                or self.projectiles):
            return False
        if not self.set_aim_target(self.aim_target):
            return False
        velocities = firing_velocities(self.aim_origin, self.aim_target, self.bp)
        self.projectiles = [Projectile(self._next_projectile_id + index, self.aim_origin, velocity)
                            for index, velocity in enumerate(velocities)]
        self._next_projectile_id += len(velocities)
        self._physics.accumulator = 0.0
        return self.transition_to(GameState.SHOT_ANIMATION)

    def advance_time(
        self, dt: float, targets: tuple[Target, ...] = ()
    ) -> tuple[HitEvent, ...]:
        """Resolve each impact synchronously; returned events are already applied."""
        if self.state is not GameState.SHOT_ANIMATION:
            return ()
        events = self._physics.advance(
            dt, self.projectiles,
            target_provider=lambda: self.combat.targets() + targets,
            on_hit=self.combat.handle_hit,
        )
        self.projectiles = [orb for orb in self.projectiles if orb.active]
        if not self.projectiles:
            self.bp = self.combat.finish_shot(self.bp)
            self.transition_to(GameState.TURN_RESOLVE)
        return events

    def snapshot(self) -> WorldSnapshot:
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
            ) if enemy.alive),
            crystals=tuple(crystal.snapshot() for crystal in sorted(
                self.crystals.values(), key=lambda crystal: crystal.crystal_id
            ) if not crystal.collected),
            pending_bp=self.pending_bp,
        )
