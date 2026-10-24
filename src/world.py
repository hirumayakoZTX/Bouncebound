"""Run data and validated scene transitions without rendering dependencies."""

from dataclasses import dataclass

from src.states import ACTIVE_STATES, GameState


# Future phases have transition contracts but no input or gameplay triggers yet.
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


class World:
    def __init__(self) -> None:
        self.reset()

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def paused_state(self) -> GameState | None:
        return self._paused_state

    def reset(self) -> None:
        """Restore the menu and all data currently owned by the run."""
        self.stage = 1
        self.turn_index = 1
        self.hp = self.max_hp = 100
        self.mp = self.max_mp = 100
        self.bp = 1
        self._state = GameState.MENU
        self._paused_state: GameState | None = None

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
        )
