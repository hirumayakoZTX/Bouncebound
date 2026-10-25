"""Stage 3 fixtures and ordinary-action campaign routes; no HP edits in clear paths."""

from src.stage_config import parse_stage
from src.states import GameState
from src.world import World, STAGE_THREE
from stage_one_fixtures import perform_action
from stage_two_fixtures import enter_stage_two, STAGE_TWO_CLEAR


ORDINARY_ROWS = (3,4,3, 2,3,2, 4,5,4, 1,2,1, 5,6,5, 2,3,2, 3)
METEOR_CLEAR = tuple(('shot',row) for row in ORDINARY_ROWS) + (
    ('shot',4),('shot',3),('meteor',3),
)
EXECUTE_CLEAR = tuple(('shot',row) for row in ORDINARY_ROWS) + (
    ('ward',3),('reraise',3),('cure',3),('shot',3),('shot',3),
)


def definition(*spawns, boss=None, capacity=25):
    entries=[dict(id=i,kind=k,col=c,row=r) for i,k,c,r in spawns]
    data=dict(schema_version=1,stage=3,capacity=capacity,
              waves=[dict(turn=1,spawns=entries or [dict(id=99,kind='crystal',col=0,row=7)])],
              completion=dict(mandatory_enemy_ids=[e['id'] for e in entries if e['kind']!='crystal']
                              + ([boss[0]] if boss else []),final=True))
    if boss:
        i,c,r=boss
        data['boss_wave']=dict(when='after_scripted_waves_cleared',escape_policy='contact_and_fail',
                               spawns=[dict(id=i,kind='odin',col=c,row=r)])
    return parse_stage(data)


def playing(stage=STAGE_THREE):
    # Small first/second stages still require genuine completed actions to advance.
    def entry(stage):
        return parse_stage(dict(schema_version=1,stage=stage,
            waves=[dict(turn=1,spawns=[dict(id=1,kind='basic',col=7,row=3)])],
            completion=dict(mandatory_enemy_ids=[1],final=False)))
    world=World(stages={1:entry(1),2:entry(2),3:stage})
    world.start_new_run();world.transition_to(GameState.PLAYER_AIM)
    for _ in range(2):
        perform_action(world,'shot',3)
        assert world.advance_stage();world.transition_to(GameState.PLAYER_AIM)
    return world


def enter_stage_three(world, *, game=None, schedule=(.25,)):
    enter_stage_two(world,game=game,schedule=schedule)
    for k,r in STAGE_TWO_CLEAR:perform_action(world,k,r,schedule,game=game)
    assert world.state is GameState.STAGE_CLEAR
    if game is None:
        assert world.advance_stage();world.transition_to(GameState.PLAYER_AIM)
    else:
        import pygame
        for _ in range(2):pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        for event in pygame.event.get():game.handle_event(event)
    assert world.stage==3 and world.turn_index==1


DEFENSE_ENDING = (
    ('shot',0,(740,456)),('shot',0,(768,456)),
    ('esuna',0,None),('levitation',0,None),('ward',0,None),('cure',0,None),('esuna',0,None),
    ('shot',1,(740,96)),('shot',1,(480,72)),('shot',0,(96,360)),
)
