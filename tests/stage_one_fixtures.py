"""Small boss fixtures and ordinary-action drivers; no HP mutation in clear paths."""

from itertools import cycle

from src.stage_config import parse_stage
from src.states import GameState
from src.world import World


OPENING_ROWS = (3, 3, 2, 2, 4, 4, 1, 1, 5)
DEFENSE_ROWS = (0,) * 12 + (1, 4, 1)


def boss_definition(*, scripted=False, col=7, rows=(2, 5), reverse=False, capacity=25):
    spawns = ([{'id': 1, 'kind': 'basic', 'col': 0, 'row': 3}] if scripted else [])
    spawns.append({'id': 2, 'kind': 'crystal', 'col': 0, 'row': 7})
    bosses = [{'id': 100, 'kind': 'ultros', 'col': col, 'row': rows[0]},
              {'id': 101, 'kind': 'typhon', 'col': col, 'row': rows[1]}]
    return parse_stage({
        'schema_version': 1, 'stage': 1, 'capacity': capacity,
        'waves': [{'turn': 1, 'spawns': spawns}],
        'boss_wave': {'when': 'after_scripted_waves_cleared',
                      'escape_policy': 'contact_and_fail',
                      'spawns': list(reversed(bosses)) if reverse else bosses},
        'completion': {'mandatory_enemy_ids': ([1] if scripted else []) + [100, 101],
                       'final': False},
    })


def playing(definition=None):
    world = World(encounter=definition) if definition is not None else World()
    world.start_new_run()
    world.transition_to(GameState.PLAYER_AIM)
    return world


def perform_action(world, kind, row, schedule=(.25,), *, game=None, resolve=True):
    """Issue free movement then a real shot/cast; optionally use posted Pygame input."""
    if game is None:
        while world.player_row != row:
            assert world.move_player(1 if world.player_row < row else -1)
        if kind == 'shot':
            assert world.set_aim_target((96, 96 + 48 * row))
            assert world.fire()
        else:
            assert world.select_spell(kind)
            assert world.cast_selected_spell().valid
    else:
        import pygame
        key = pygame.K_DOWN if world.player_row < row else pygame.K_UP
        events = [pygame.event.Event(pygame.KEYDOWN, key=key)
                  for _ in range(abs(world.player_row - row))]
        if kind == 'shot':
            target = (96, 96 + 48 * row)
            events += [pygame.event.Event(pygame.MOUSEMOTION, pos=target),
                       pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=target)]
        else:
            from src.spells import SpellId
            number = list(SpellId).index(SpellId(kind)) + 1
            events += [pygame.event.Event(pygame.KEYDOWN, key=getattr(pygame, f'K_{number}')),
                       pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)]
        for event in events:
            pygame.event.post(event)
        for event in pygame.event.get():
            game.handle_event(event)
    assert world.state in (GameState.SHOT_ANIMATION, GameState.SPELL_ANIMATION)
    hits = []
    for index, dt in enumerate(cycle(schedule)):
        hits.extend(world.advance_time(dt))
        if world.state is GameState.TURN_RESOLVE:
            break
        assert index < 2000
    if resolve:
        assert world.resolve_turn()
    return tuple(hits)


def clear_ordinary_waves(world, schedule=(.25,), *, game=None):
    for row in OPENING_ROWS:
        perform_action(world, 'shot', row, schedule, game=game)
    assert world.turn_index == 10 and world.encounter.boss_wave_spawned
