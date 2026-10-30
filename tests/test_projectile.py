"""Deterministic swept geometry, orb lifecycle, and fixed-step tests."""

from math import hypot, sqrt
import unittest
from unittest.mock import patch

from src.collision import Bounds, Target, sweep_circle
from src.constants import MAX_PHYSICS_STEPS, PHYSICS_STEP
from src.projectile import FixedStepPhysics, Projectile


class ProjectileTests(unittest.TestCase):
    def test_launch_normalizes_direction_and_preserves_origin(self) -> None:
        for target in ((300, 240), (768, 72), (768, 456), (96, 72)):
            with self.subTest(target=target):
                orb = Projectile.launch(4, (808, 240), target)
                self.assertEqual(orb.position, (808, 240))
                self.assertAlmostEqual(hypot(*orb.velocity), 520)
                self.assertLess(orb.velocity[0], 0)
                self.assertEqual((orb.radius, orb.damage, orb.max_hits, orb.max_lifetime),
                                 (7, 4, 12, 5))
                self.assertFalse(orb.entered_arena)

    def test_invalid_launch_directions_are_rejected(self) -> None:
        for target in ((808, 240), (808, 100), (900, 240), (float("nan"), 240)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                Projectile.launch(1, (808, 240), target)

    def test_entry_does_not_teleport_or_bounce_on_the_initial_right_gap(self) -> None:
        orb = Projectile.launch(1, (808, 240), (300, 240))
        orb.step(PHYSICS_STEP)
        self.assertAlmostEqual(orb.position[0], 808 - 520 * PHYSICS_STEP)
        self.assertEqual(orb.position[1], 240)
        self.assertFalse(orb.entered_arena)
        self.assertTrue(orb.active)
        self.assertEqual(orb.velocity, (-520, 0))
        for _ in range(11):
            orb.step(PHYSICS_STEP)
        self.assertTrue(orb.entered_arena)
        self.assertLessEqual(orb.position[0], 761)

    def test_entry_corridor_handles_shallow_and_steep_angles_from_all_rows(self) -> None:
        for row in (0, 3, 7):
            for target in ((96, 72), (768, 72), (96, 456), (768, 456)):
                with self.subTest(row=row, target=target):
                    orb = Projectile.launch(1, (808, 96 + 48 * row), target)
                    for _ in range(120):
                        previous_x = orb.position[0]
                        previously_entered = orb.entered_arena
                        orb.step(PHYSICS_STEP)
                        self.assertTrue(orb.active)
                        self.assertTrue(79 - 1e-7 <= orb.position[1] <= 449 + 1e-7)
                        if not previously_entered and not orb.entered_arena:
                            self.assertLessEqual(orb.position[0], previous_x)
                    self.assertTrue(orb.entered_arena)

    def test_top_bounce_can_happen_before_full_arena_entry(self) -> None:
        orb = Projectile.launch(1, (808, 240), (768, 72))
        for _ in range(40):
            orb.step(PHYSICS_STEP)
        self.assertGreater(orb.position[0], 761)
        self.assertFalse(orb.entered_arena)
        self.assertLess(orb.velocity[0], 0)
        self.assertGreater(orb.velocity[1], 0)

    def test_all_four_walls_reflect_the_correct_component(self) -> None:
        cases = (
            ((104, 200), (-520, 0), (520, 0)),
            ((760, 200), (520, 0), (-520, 0)),
            ((300, 80), (0, -520), (0, 520)),
            ((300, 448), (0, 520), (0, -520)),
        )
        for position, velocity, expected in cases:
            with self.subTest(position=position):
                orb = Projectile(1, position, velocity)
                orb.step(PHYSICS_STEP)
                self.assertEqual(orb.velocity, expected)
                self.assertTrue(orb.arena.inset(7).contains(orb.position))
                self.assertEqual(orb.hits, 0)

    def test_corner_contacts_reverse_both_components_without_sticking(self) -> None:
        speed = 520 / sqrt(2)
        for x, y, sx, sy in ((108, 84, -1, -1), (756, 84, 1, -1),
                             (108, 444, -1, 1), (756, 444, 1, 1)):
            with self.subTest(corner=(sx, sy)):
                orb = Projectile(1, (x, y), (sx * speed, sy * speed))
                for _ in range(4):
                    orb.step(PHYSICS_STEP)
                self.assertAlmostEqual(orb.velocity[0], -sx * speed)
                self.assertAlmostEqual(orb.velocity[1], -sy * speed)
                self.assertTrue(orb.arena.inset(7).contains(orb.position))

    def test_wall_bounces_do_not_consume_the_target_hit_limit(self) -> None:
        orb = Projectile(1, (15, 15), (520, 0), arena=Bounds(0, 0, 30, 30))
        for _ in range(120):
            orb.step(PHYSICS_STEP)
        self.assertTrue(orb.active)
        self.assertEqual(orb.hits, 0)

    def test_face_collision_reflects_and_returns_combat_event_data(self) -> None:
        target = Target(8, Bounds(250, 180, 270, 220))
        orb = Projectile(4, (200, 200), (520, 0))
        events = orb.step(0.2, (target,))
        self.assertEqual(len(events), 1)
        hit = events[0]
        self.assertEqual((hit.projectile_id, hit.target_id, hit.damage), (4, 8, 4))
        self.assertEqual(hit.normal, (-1, 0))
        self.assertEqual(hit.position, (243, 200))
        self.assertAlmostEqual(orb.position[0], 182)
        self.assertEqual(orb.velocity, (-520, 0))

    def test_near_tangent_corner_contact_preserves_speed(self) -> None:
        target = Target(1, Bounds(250, 180, 270, 220))
        orb = Projectile(1, (240, 173.01), (520, 0))
        events = orb.step(0.04, (target,))
        self.assertEqual(len(events), 1)
        self.assertLess(events[0].normal[0], 0)
        self.assertLess(events[0].normal[1], -0.99)
        self.assertAlmostEqual(hypot(*orb.velocity), 520)

    def test_exact_tangent_does_not_count_as_a_target_hit(self) -> None:
        target = Target(1, Bounds(250, 180, 270, 220))
        orb = Projectile(1, (240, 173), (520, 0))
        events = orb.step(0.04, (target,))
        self.assertEqual(events, ())
        self.assertEqual(orb.hits, 0)
        self.assertEqual(orb.velocity, (520, 0))
        for _ in range(3):
            self.assertEqual(orb.step(PHYSICS_STEP, (target,)), ())

    def test_rounded_corner_does_not_report_expanded_box_false_positive(self) -> None:
        contact = sweep_circle((240, 174), (520, 0), 7, Bounds(250, 180, 270, 220), 0.01)
        self.assertIsNone(contact)

    def test_fast_orb_does_not_tunnel_through_a_thin_target(self) -> None:
        target = Target(1, Bounds(250, 180, 250.01, 220))
        orb = Projectile(1, (200, 200), (100_000, 0))
        events = orb.step(PHYSICS_STEP, (target,))
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0].position, (243, 200))

    def test_persistent_overlap_emits_once_until_separation(self) -> None:
        target = Target(1, Bounds(250, 180, 270, 220))
        orb = Projectile(1, (243 - 520 * PHYSICS_STEP, 200), (520, 0))
        self.assertEqual(len(orb.step(PHYSICS_STEP, (target,))), 1)
        orb.velocity = (0, 0)
        for _ in range(10):
            self.assertEqual(orb.step(PHYSICS_STEP, (target,)), ())
        self.assertEqual(orb.hits, 1)
        self.assertEqual(orb.contact_ids, {1})

    def test_separation_and_return_can_hit_the_same_target_again(self) -> None:
        orb = Projectile(1, (20, 50), (520, 0), arena=Bounds(0, 0, 100, 100))
        target = Target(9, Bounds(50, 40, 51, 60))
        events = []
        for _ in range(30):
            events.extend(orb.step(PHYSICS_STEP, (target,)))
        self.assertEqual([event.target_id for event in events], [9, 9])

    def test_removed_target_clears_contact_tracking(self) -> None:
        orb = Projectile(1, (250, 180), (0, 0))
        target = Target(1, Bounds(250, 180, 270, 220))
        orb.step(PHYSICS_STEP, (target,))
        self.assertEqual(orb.step(PHYSICS_STEP), ())
        self.assertEqual(orb.contact_ids, set())

    def test_neighboring_simultaneous_targets_have_stable_id_order(self) -> None:
        targets = (Target(2, Bounds(250, 200, 270, 220)),
                   Target(1, Bounds(250, 180, 270, 200)))
        snapshots = []
        for ordered in (targets, tuple(reversed(targets))):
            orb = Projectile(1, (200, 200), (520, 0))
            events = orb.step(0.1, ordered)
            self.assertEqual([event.target_id for event in events], [1, 2])
            self.assertEqual(orb.velocity, (-520, 0))
            snapshots.append(orb.snapshot())
        self.assertEqual(snapshots[0], snapshots[1])

    def test_multiple_projectiles_contact_the_same_target_independently(self) -> None:
        orbs = [Projectile(i, (240, 200), (520, 0)) for i in (1, 2)]
        events = FixedStepPhysics().advance(0.02, orbs, (Target(7, Bounds(250, 180, 270, 220)),))
        self.assertEqual([(event.projectile_id, event.target_id) for event in events],
                         [(1, 7), (2, 7)])
        self.assertIsNot(orbs[0].contact_ids, orbs[1].contact_ids)

    def test_lifetime_termination_is_once_and_inactive_orbs_do_nothing(self) -> None:
        orb = Projectile.launch(1, (808, 240), (300, 200))
        physics = FixedStepPhysics()
        for _ in range(300):
            physics.advance(1 / 60, [orb])
        self.assertFalse(orb.active)
        self.assertEqual(orb.age, 5)
        before = orb.snapshot()
        self.assertEqual(orb.step(100), ())
        self.assertEqual(physics.advance(100, [orb]), ())
        self.assertEqual(orb.snapshot(), before)

    def test_maximum_successful_hits_terminates_once(self) -> None:
        orb = Projectile(1, (20, 50), (520, 0), arena=Bounds(0, 0, 100, 100))
        target = Target(9, Bounds(50, 40, 51, 60))
        events = []
        physics = FixedStepPhysics()
        for _ in range(150):
            events.extend(physics.advance(1 / 60, [orb], (target,)))
        self.assertEqual(len(events), 12)
        self.assertEqual(orb.hits, 12)
        self.assertFalse(orb.active)
        self.assertLess(orb.age, 5)
        before = orb.snapshot()
        self.assertEqual(orb.step(PHYSICS_STEP, (target,)), ())
        self.assertEqual(orb.snapshot(), before)

    def test_post_entry_outside_position_terminates_without_further_events(self) -> None:
        orb = Projectile(1, (300, 200), (520, 0))
        orb.position = (800, 200)
        self.assertEqual(orb.step(PHYSICS_STEP), ())
        self.assertFalse(orb.active)
        self.assertEqual(orb.age, 0)

    def test_rendering_schedules_produce_the_same_simulation(self) -> None:
        results = []
        schedules = [[1 / fps] * (2 * fps) for fps in (30, 60, 144)]
        schedules.append([0.005, 0.047, 0.003, 0.011, 0.020, 0.014] * 20)
        for schedule in schedules:
            orb = Projectile.launch(1, (808, 240), (300, 100))
            physics = FixedStepPhysics()
            events = []
            for interval in schedule:
                events.extend(physics.advance(interval, [orb], (
                    Target(1, Bounds(400, 100, 430, 140)),
                )))
            results.append((orb.snapshot(), events))
        for snapshot, events in results[1:]:
            self.assertAlmostEqual(snapshot.age, results[0][0].age)
            for actual, expected in zip(snapshot.position, results[0][0].position):
                self.assertAlmostEqual(actual, expected, places=8)
            self.assertEqual(snapshot.velocity, results[0][0].velocity)
            self.assertEqual(events, results[0][1])

    def test_large_frame_has_bounded_steps_and_no_deferred_backlog(self) -> None:
        orb = Projectile.launch(1, (808, 240), (300, 240))
        physics = FixedStepPhysics()
        with patch.object(orb, "step", wraps=orb.step) as step:
            physics.advance(1e100, [orb])
            self.assertEqual(step.call_count, MAX_PHYSICS_STEPS)
        self.assertAlmostEqual(orb.age, 0.25)
        self.assertAlmostEqual(orb.position[0], 678)
        self.assertLess(physics.accumulator, PHYSICS_STEP)
        before = orb.snapshot()
        physics.advance(0, [orb])
        self.assertEqual(orb.snapshot(), before)

    def test_frame_time_and_duplicate_target_ids_are_validated(self) -> None:
        orb = Projectile.launch(1, (808, 240), (300, 240))
        physics = FixedStepPhysics()
        for interval in (-1, float("inf"), float("nan")):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                physics.advance(interval, [orb])
        target = Target(1, Bounds(250, 180, 270, 220))
        with self.assertRaisesRegex(ValueError, "unique stable IDs"):
            physics.advance(0.1, [orb], (target, target))


if __name__ == "__main__":
    unittest.main()
