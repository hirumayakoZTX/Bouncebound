"""Temporary Stage 1 prototype data, independent of the final encounter."""

from src.encounter import EncounterDefinition, Spawn, Wave


PROTOTYPE = EncounterDefinition(stage=1, waves=(
    Wave(turn=1, spawns=(
        Spawn(1, "basic", 2, 3), Spawn(2, "bomb", 3, 3), Spawn(3, "bomb", 4, 3),
        Spawn(4, "basic", 2, 4), Spawn(5, "basic", 3, 4), Spawn(6, "basic", 4, 4),
        Spawn(7, "crystal", 10, 3),
    )),
    Wave(turn=3, spawns=(
        Spawn(8, "basic", 2, 2), Spawn(9, "bomb", 3, 2), Spawn(10, "bomb", 4, 2),
        Spawn(11, "basic", 2, 3), Spawn(12, "basic", 3, 3), Spawn(13, "basic", 4, 3),
        Spawn(14, "crystal", 9, 2),
    )),
    Wave(turn=5, spawns=(
        Spawn(15, "basic", 2, 4), Spawn(16, "bomb", 3, 4), Spawn(17, "bomb", 4, 4),
        Spawn(18, "basic", 2, 5), Spawn(19, "basic", 3, 5), Spawn(20, "basic", 4, 5),
        Spawn(21, "crystal", 8, 4),
    )),
    Wave(turn=7, spawns=(
        Spawn(22, "basic", 2, 3), Spawn(23, "bomb", 3, 3), Spawn(24, "bomb", 4, 3),
        Spawn(25, "basic", 2, 4), Spawn(26, "basic", 3, 4), Spawn(27, "basic", 4, 4),
        Spawn(28, "crystal", 11, 3),
    )),
))
