"""Stage 2 fixtures and reproducible ordinary-action campaign paths."""

from src.stage_config import parse_stage
from src.states import GameState
from src.world import STAGE_TWO, World
from stage_one_fixtures import OPENING_ROWS, perform_action


STAGE_TWO_CLEAR = (
    ('shot', 3), ('shot', 0), ('shot', 0), ('starstorm', 1),
    ('shot', 0), ('shot', 0), ('shot', 7), ('shot', 0), ('shot', 0),
    ('shot', 1), ('shot', 0), ('shot', 0), ('shot', 5), ('shot', 0),
    ('shot', 0), ('shot', 3), ('shot', 0), ('shot', 3),
)


def definition(*spawns, boss=None, capacity=25):
    entries = [dict(id=i, kind=kind, col=col, row=row) for i, kind, col, row in spawns]
    data = dict(schema_version=1, stage=2, capacity=capacity,
                waves=[dict(turn=1, spawns=entries or [dict(id=99, kind='crystal', col=0, row=7)])],
                completion=dict(mandatory_enemy_ids=[s['id'] for s in entries if s['kind'] != 'crystal']
                                + ([boss[0]] if boss else []), final=False))
    if boss:
        i, col, row = boss
        data['boss_wave'] = dict(when='after_scripted_waves_cleared',
                                spawns=[dict(id=i, kind='chichu', col=col, row=row)])
    return parse_stage(data)


def playing(stage=STAGE_TWO):
    # A real authorized Stage 1 clear leads to the isolated Stage 2 fixture.
    first = parse_stage(dict(schema_version=1, stage=1,
                             waves=[dict(turn=1, spawns=[dict(id=1, kind='basic', col=7, row=3)])],
                             completion=dict(mandatory_enemy_ids=[1], final=False)))
    world = World(stages={1: first, 2: stage})
    world.start_new_run(); world.transition_to(GameState.PLAYER_AIM)
    perform_action(world, 'shot', 3)
    assert world.advance_stage()
    world.transition_to(GameState.PLAYER_AIM)
    return world


def enter_stage_two(world, *, game=None, schedule=(.25,)):
    for row in OPENING_ROWS + (2, 5):
        perform_action(world, 'shot', row, schedule, game=game)
    assert world.state is GameState.STAGE_CLEAR
    if game is None:
        assert world.advance_stage()
        world.transition_to(GameState.PLAYER_AIM)
    else:
        import pygame
        for _ in range(2):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        for event in pygame.event.get():
            game.handle_event(event)
    assert world.stage == 2 and world.turn_index == 1


# Ordinary click targets that deliberately miss Chichu until its defense-line escape.
DEFENSE_AIMS = (
    (0, (240, 72)), (5, (650, 360)), (5, (650, 360)), (0, (740, 72)),
    (1, (740, 96)), (1, (480, 72)), (0, (96, 360)),
)


def perform_aimed_shot(world, row, target, schedule=(.25,), *, game=None):
    from itertools import cycle
    while world.player_row != row:
        if game is None:
            assert world.move_player(1 if world.player_row < row else -1)
        else:
            import pygame
            before=world.player_row
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN,
                key=pygame.K_DOWN if before < row else pygame.K_UP))
            for event in pygame.event.get():game.handle_event(event)
            assert world.player_row != before
    if game is None:
        assert world.set_aim_target(target) and world.fire()
    else:
        import pygame
        pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION,pos=target))
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=target))
        for event in pygame.event.get():game.handle_event(event)
        assert world.state is GameState.SHOT_ANIMATION
    for index,dt in enumerate(cycle(schedule)):
        world.advance_time(dt)
        if world.state is GameState.TURN_RESOLVE:break
        assert index < 2000
    assert world.resolve_turn()
