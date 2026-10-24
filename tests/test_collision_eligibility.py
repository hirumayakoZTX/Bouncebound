"""Regressions separating physical impacts from touching and recovery."""

from math import hypot, sqrt
import unittest

from src.collision import Bounds, EPSILON, Target, sweep_circle
from src.constants import PHYSICS_STEP
from src.projectile import Projectile


class CollisionEligibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.target = Target(target_id=42, bounds=Bounds(200, 200, 248, 248))

    def test_exact_reproduction_touching_left_face_while_moving_away(self) -> None:
        orb = Projectile(projectile_id=1, position=(193, 220), velocity=(-520, 0))
        events = orb.step(1 / 120, (self.target,))
        self.assertEqual(events, ())
        self.assertEqual(orb.hits, 0)
        self.assertEqual(orb.velocity, (-520, 0))
        self.assertAlmostEqual(orb.position[0], 193 - 520 / 120)
        self.assertEqual(orb.position[1], 220)
        self.assertAlmostEqual(orb.age, 1 / 120)

    def test_initial_surface_tangency_and_stationary_touch_are_not_impacts(self) -> None:
        for velocity in ((0, 520), (0, -520), (0, 0)):
            with self.subTest(velocity=velocity):
                orb = Projectile(1, (193, 220), velocity)
                self.assertEqual(orb.step(PHYSICS_STEP, (self.target,)), ())
                self.assertEqual(orb.hits, 0)
                self.assertEqual(orb.velocity, velocity)

    def test_approaching_surface_at_time_zero_is_a_valid_damage_event(self) -> None:
        orb = Projectile(1, (193, 220), (520, 0))
        events = orb.step(PHYSICS_STEP, (self.target,))
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].projectile_id, events[0].target_id, events[0].damage),
                         (1, 42, 5))
        self.assertEqual(events[0].position, (193, 220))
        self.assertEqual(orb.hits, 1)
        self.assertEqual(orb.velocity, (-520, 0))
        self.assertAlmostEqual(orb.age, PHYSICS_STEP)

    def test_valid_swept_face_impact_from_separation_is_preserved(self) -> None:
        orb = Projectile(1, (180, 220), (520, 0))
        events = orb.step(1 / 30, (self.target,))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].position, (193, 220))
        self.assertEqual(events[0].normal, (-1, 0))
        self.assertEqual(events[0].damage, 5)
        self.assertEqual(orb.hits, 1)
        self.assertEqual(orb.velocity, (-520, 0))

    def test_slight_penetration_recovers_without_creating_damage(self) -> None:
        for velocity, expected_velocity in (
            ((-520, 0), (-520, 0)),
            ((0, 520), (0, 520)),
            ((520, 0), (-520, 0)),
        ):
            with self.subTest(velocity=velocity):
                orb = Projectile(1, (193.0001, 220), velocity)
                self.assertEqual(orb.step(PHYSICS_STEP, (self.target,)), ())
                self.assertEqual(orb.hits, 0)
                self.assertEqual(orb.velocity, expected_velocity)
                self.assertAlmostEqual(orb.position[0], 193 + expected_velocity[0] * PHYSICS_STEP)
                self.assertAlmostEqual(hypot(*orb.velocity), 520)
                self.assertAlmostEqual(orb.age, PHYSICS_STEP)

    def test_deep_penetration_recovers_deterministically_without_damage(self) -> None:
        orb = Projectile(1, (224, 224), (0, 0))
        self.assertEqual(orb.step(PHYSICS_STEP, (self.target,)), ())
        self.assertEqual(orb.position, (193, 224))
        for _ in range(4):
            self.assertEqual(orb.step(PHYSICS_STEP, (self.target,)), ())
        self.assertEqual(orb.hits, 0)
        self.assertEqual(orb.contact_ids, {42})
        self.assertAlmostEqual(orb.age, 5 * PHYSICS_STEP)

    def test_surface_noise_and_negligible_normal_velocity_do_not_create_damage(self) -> None:
        for offset in (-0.25 * EPSILON, 0.0, 0.25 * EPSILON):
            with self.subTest(offset=offset):
                orb = Projectile(1, (193 + offset, 220), (1e-10, 520))
                self.assertEqual(orb.step(PHYSICS_STEP, (self.target,)), ())
                self.assertEqual(orb.hits, 0)
                self.assertEqual(orb.velocity, (1e-10, 520))

    def test_touching_rounded_corner_requires_inward_velocity(self) -> None:
        diagonal = 1 / sqrt(2)
        position = (200 - 7 * diagonal, 200 - 7 * diagonal)
        for velocity, expected_hits in (
            ((-520 * diagonal, -520 * diagonal), 0),
            ((-520 * diagonal, 520 * diagonal), 0),
            ((520 * diagonal, 520 * diagonal), 1),
        ):
            with self.subTest(velocity=velocity):
                orb = Projectile(1, position, velocity)
                events = orb.step(PHYSICS_STEP, (self.target,))
                self.assertEqual(len(events), expected_hits)
                self.assertEqual(orb.hits, expected_hits)
                self.assertAlmostEqual(hypot(*orb.velocity), 520)
                self.assertAlmostEqual(orb.age, PHYSICS_STEP)

    def test_separated_near_tangent_corner_impact_still_emits_damage(self) -> None:
        orb = Projectile(1, (190, 193.01), (520, 0))
        events = orb.step(0.04, (self.target,))
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].target_id, events[0].damage), (42, 5))
        self.assertLess(events[0].normal[0], 0)
        self.assertLess(events[0].normal[1], -0.99)
        self.assertAlmostEqual(hypot(*orb.velocity), 520)

    def test_swept_exact_tangency_is_not_an_impact(self) -> None:
        orb = Projectile(1, (180, 193), (520, 0))
        self.assertEqual(orb.step(0.1, (self.target,)), ())
        self.assertEqual(orb.hits, 0)
        self.assertEqual(orb.velocity, (520, 0))
        self.assertAlmostEqual(orb.position[0], 232)

    def test_valid_hit_followed_by_sustained_contact_does_not_repeat_damage(self) -> None:
        orb = Projectile(1, (193 - 520 * PHYSICS_STEP, 220), (520, 0))
        self.assertEqual(len(orb.step(PHYSICS_STEP, (self.target,))), 1)
        self.assertEqual(orb.contact_ids, {42})
        orb.velocity = (0, 520)
        for _ in range(5):
            self.assertEqual(orb.step(PHYSICS_STEP, (self.target,)), ())
        self.assertEqual(orb.hits, 1)

    def test_departing_then_returning_after_wall_bounce_counts_only_the_real_hit(self) -> None:
        orb = Projectile(1, (193, 220), (-520, 0))
        events = orb.step(0.4, (self.target,))
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].target_id, events[0].damage), (42, 5))
        self.assertEqual(orb.hits, 1)
        self.assertEqual(orb.velocity, (-520, 0))

    def test_false_contact_cannot_consume_the_last_hit_or_end_the_orb(self) -> None:
        orb = Projectile(1, (193, 220), (-520, 0), max_hits=1)
        self.assertEqual(orb.step(PHYSICS_STEP, (self.target,)), ())
        self.assertEqual(orb.hits, 0)
        self.assertTrue(orb.active)
        self.assertAlmostEqual(orb.age, PHYSICS_STEP)

    def test_sweep_rejects_nonapproaching_surface_contact_directly(self) -> None:
        for velocity in ((-520, 0), (0, 520), (0, 0)):
            with self.subTest(velocity=velocity):
                self.assertIsNone(sweep_circle((193, 220), velocity, 7,
                                               self.target.bounds, PHYSICS_STEP))


if __name__ == "__main__":
    unittest.main()
