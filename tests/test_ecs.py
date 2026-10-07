"""Terminal-runnable test suite for the local ECS core.

Run with:  python3 -m unittest discover -s tests -v
No game window, engine, server or database is involved.
"""

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from ecs import (
    CommandBuffer,
    ComponentAlreadyExistsError,
    ComponentNotFoundError,
    EntityNotAliveError,
    System,
    World,
)


@dataclass
class Position:
    x: float = 0.0
    y: float = 0.0


@dataclass
class Velocity:
    dx: float = 0.0
    dy: float = 0.0


@dataclass
class Health:
    hp: int = 100


class MovementSystem(System):
    def update(self, world, dt):
        for _entity, pos, vel in world.query(Position, Velocity):
            pos.x += vel.dx * dt
            pos.y += vel.dy * dt


class TestEntityLifecycle(unittest.TestCase):
    def test_create_entities_have_unique_handles(self):
        world = World()
        e1, e2 = world.create_entity(), world.create_entity()
        self.assertNotEqual(e1, e2)
        self.assertTrue(world.is_alive(e1))
        self.assertTrue(world.is_alive(e2))
        self.assertEqual(world.entities(), [e1, e2])

    def test_destroy_entity(self):
        world = World()
        e = world.create_entity()
        world.destroy_entity(e)
        self.assertFalse(world.is_alive(e))
        self.assertEqual(world.entities(), [])

    def test_destroy_removes_components(self):
        world = World()
        e = world.create_entity()
        world.add_component(e, Position(1, 2))
        world.destroy_entity(e)
        self.assertEqual(list(world.query(Position)), [])

    def test_destroy_stale_handle_raises(self):
        world = World()
        e = world.create_entity()
        world.destroy_entity(e)
        with self.assertRaises(EntityNotAliveError):
            world.destroy_entity(e)
        with self.assertRaises(EntityNotAliveError):
            world.add_component(e, Position())


class TestIdReuseProtection(unittest.TestCase):
    def test_recycled_id_bumps_generation(self):
        world = World()
        old = world.create_entity()
        world.destroy_entity(old)
        new = world.create_entity()
        self.assertEqual(old.id, new.id)  # slot recycled
        self.assertNotEqual(old.generation, new.generation)
        self.assertFalse(world.is_alive(old))
        self.assertTrue(world.is_alive(new))

    def test_stale_handle_cannot_touch_recycled_entity(self):
        world = World()
        old = world.create_entity()
        world.add_component(old, Position(1, 1))
        world.destroy_entity(old)
        new = world.create_entity()
        world.add_component(new, Position(9, 9))
        # The stale handle must not read, modify or delete the new entity.
        with self.assertRaises(EntityNotAliveError):
            world.get_component(old, Position)
        with self.assertRaises(EntityNotAliveError):
            world.set_component(old, Position(0, 0))
        with self.assertRaises(EntityNotAliveError):
            world.remove_component(old, Position)
        with self.assertRaises(EntityNotAliveError):
            world.destroy_entity(old)
        # New entity is untouched.
        self.assertEqual(world.get_component(new, Position), Position(9, 9))


class TestComponentOperations(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.e = self.world.create_entity()

    def test_add_get_modify_remove(self):
        self.world.add_component(self.e, Position(1, 2))
        pos = self.world.get_component(self.e, Position)
        self.assertEqual(pos, Position(1, 2))
        pos.x = 42  # mutate in place
        self.assertEqual(self.world.get_component(self.e, Position).x, 42)
        self.world.set_component(self.e, Position(7, 8))  # replace
        self.assertEqual(self.world.get_component(self.e, Position), Position(7, 8))
        self.world.remove_component(self.e, Position)
        self.assertFalse(self.world.has_component(self.e, Position))
        self.assertIsNone(self.world.try_get(self.e, Position))

    def test_multiple_component_types_on_one_entity(self):
        self.world.add_component(self.e, Position(1, 2))
        self.world.add_component(self.e, Velocity(3, 4))
        self.world.add_component(self.e, Health(50))
        self.assertEqual(self.world.get_component(self.e, Velocity), Velocity(3, 4))
        self.assertEqual(self.world.get_component(self.e, Health).hp, 50)

    def test_duplicate_add_is_rejected(self):
        self.world.add_component(self.e, Position(1, 2))
        with self.assertRaises(ComponentAlreadyExistsError):
            self.world.add_component(self.e, Position(3, 4))
        # Still exactly one, deterministic state.
        self.assertEqual(self.world.get_component(self.e, Position), Position(1, 2))

    def test_missing_component_raises(self):
        with self.assertRaises(ComponentNotFoundError):
            self.world.get_component(self.e, Position)
        with self.assertRaises(ComponentNotFoundError):
            self.world.remove_component(self.e, Position)


class TestQuery(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.e1 = self.world.create_entity()  # Position + Velocity
        self.world.add_component(self.e1, Position(0, 0))
        self.world.add_component(self.e1, Velocity(1, 1))
        self.e2 = self.world.create_entity()  # Position only
        self.world.add_component(self.e2, Position(5, 5))
        self.e3 = self.world.create_entity()  # Position + Velocity + Health
        self.world.add_component(self.e3, Position(9, 9))
        self.world.add_component(self.e3, Velocity(2, 2))
        self.world.add_component(self.e3, Health(10))

    def test_single_component_query(self):
        result = {e for e, _pos in self.world.query(Position)}
        self.assertEqual(result, {self.e1, self.e2, self.e3})

    def test_multi_component_query(self):
        result = {e for e, _p, _v in self.world.query(Position, Velocity)}
        self.assertEqual(result, {self.e1, self.e3})

    def test_query_result_order_matches_type_order(self):
        for _e, vel, pos in self.world.query(Velocity, Position):
            self.assertIsInstance(vel, Velocity)
            self.assertIsInstance(pos, Position)

    def test_query_with_no_matches(self):
        self.assertEqual(list(self.world.query(Health, Velocity, Position)), [
            (self.e3, Health(10), Velocity(2, 2), Position(9, 9))
        ])
        world = World()
        self.assertEqual(list(world.query(Position)), [])

    def test_query_requires_types(self):
        with self.assertRaises(ValueError):
            list(self.world.query())


class TestIterationSafety(unittest.TestCase):
    def test_destroy_entity_during_iteration(self):
        world = World()
        entities = []
        for i in range(5):
            e = world.create_entity()
            world.add_component(e, Position(i, i))
            entities.append(e)

        visited = []

        class KillerSystem(System):
            def update(self, w, dt):
                for e, _pos in w.query(Position):
                    visited.append(e)
                    w.destroy_entity(e)  # structural change mid-iteration

        world.add_system(KillerSystem())
        world.step()
        self.assertEqual(visited, entities)  # every match visited exactly once
        self.assertEqual(world.entities(), [])
        self.assertEqual(list(world.query(Position)), [])

    def test_add_and_remove_component_during_iteration(self):
        world = World()
        for i in range(3):
            e = world.create_entity()
            world.add_component(e, Position(i, i))

        visited = []

        class MutatingSystem(System):
            def update(self, w, dt):
                for e, pos in w.query(Position):
                    visited.append(e)
                    w.remove_component(e, Position)
                    w.add_component(e, Velocity(1, 1))

        world.add_system(MutatingSystem())
        world.step()  # must not raise or skip/revisit rows
        self.assertEqual(len(visited), 3)
        self.assertEqual(list(world.query(Position)), [])
        self.assertEqual(len(list(world.query(Velocity))), 3)


class TestSystemOrder(unittest.TestCase):
    def test_systems_run_in_registration_order(self):
        world = World()
        calls = []

        class Recorder(System):
            def __init__(self, tag):
                self.tag = tag

            def update(self, w, dt):
                calls.append(self.tag)

        world.add_system(Recorder("first"))
        world.add_system(Recorder("second"))
        world.add_system(Recorder("third"))
        world.step()
        self.assertEqual(calls, ["first", "second", "third"])

    def test_movement_system_updates_matching_entities(self):
        world = World()
        e = world.create_entity()
        world.add_component(e, Position(0, 0))
        world.add_component(e, Velocity(2, 3))
        still = world.create_entity()
        world.add_component(still, Position(7, 7))
        world.add_system(MovementSystem())
        world.step(dt=0.5)
        self.assertEqual(world.get_component(e, Position), Position(1.0, 1.5))
        self.assertEqual(world.get_component(still, Position), Position(7, 7))


class TestCommandBuffer(unittest.TestCase):
    def test_commands_are_deferred_until_flush(self):
        world = World()
        e = world.create_entity()
        buf = CommandBuffer()
        buf.add_component(e, Position(1, 2))
        buf.create_entity()
        self.assertFalse(world.has_component(e, Position))
        self.assertEqual(len(world.entities()), 1)
        created = world.flush(buf)
        self.assertTrue(world.has_component(e, Position))
        self.assertEqual(len(created), 1)
        self.assertTrue(world.is_alive(created[0]))
        self.assertEqual(len(buf), 0)

    def test_deferred_destroy_and_remove(self):
        world = World()
        e1 = world.create_entity()
        e2 = world.create_entity()
        world.add_component(e1, Health(5))
        buf = CommandBuffer()
        buf.remove_component(e1, Health)
        buf.destroy_entity(e2)
        world.flush(buf)
        self.assertFalse(world.has_component(e1, Health))
        self.assertFalse(world.is_alive(e2))

    def test_system_using_command_buffer_during_iteration(self):
        world = World()
        for i in range(4):
            e = world.create_entity()
            world.add_component(e, Health(i))
        buf = CommandBuffer()

        class CullSystem(System):
            def update(self, w, dt):
                for e, health in w.query(Health):
                    if health.hp < 2:
                        buf.destroy_entity(e)  # deferred, iteration is safe

        world.add_system(CullSystem())
        world.step()
        self.assertEqual(len(world.entities()), 4)  # nothing applied yet
        world.flush(buf)
        self.assertEqual(len(world.entities()), 2)


class TestSnapshot(unittest.TestCase):
    def _build_world(self):
        world = World()
        world.register_component(Position)
        world.register_component(Velocity)
        world.register_component(Health)
        e1 = world.create_entity()
        world.add_component(e1, Position(1, 2))
        world.add_component(e1, Velocity(3, 4))
        e2 = world.create_entity()
        world.add_component(e2, Health(55))
        # Destroy one entity so the free list / generations are non-trivial.
        e3 = world.create_entity()
        world.add_component(e3, Position(8, 8))
        world.destroy_entity(e3)
        return world

    def test_snapshot_restore_roundtrip(self):
        world = self._build_world()
        snap = world.snapshot()
        before_entities = world.entities()
        before_query = sorted(
            (e, p, v) for e, p, v in world.query(Position, Velocity)
        )

        restored = World()
        restored.register_component(Position)
        restored.register_component(Velocity)
        restored.register_component(Health)
        restored.restore(snap)

        self.assertEqual(restored.entities(), before_entities)
        self.assertEqual(
            sorted((e, p, v) for e, p, v in restored.query(Position, Velocity)),
            before_query,
        )
        self.assertEqual(restored.snapshot(), snap)

    def test_restore_preserves_generation_protection(self):
        world = self._build_world()
        snap = world.snapshot()
        restored = World.from_snapshot(snap)
        # Recycled slot keeps its bumped generation after restore.
        stale = world.entities()[0]
        world.destroy_entity(stale)
        self.assertFalse(restored.is_alive(stale.__class__(stale.id, stale.generation + 1)))
        new = restored.create_entity()
        self.assertTrue(restored.is_alive(new))

    def test_snapshot_is_isolated_from_later_mutation(self):
        world = self._build_world()
        snap = world.snapshot()
        e = world.entities()[0]
        world.get_component(e, Position).x = 999
        restored = World.from_snapshot(snap)
        self.assertEqual(restored.get_component(e, Position).x, 1)

    def test_save_and_load_json_file(self):
        world = self._build_world()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "world.json"
            world.save_snapshot(path)
            data = json.loads(path.read_text())
            self.assertIn("components", data)
            loaded = World.load_snapshot(path)
            self.assertEqual(loaded.snapshot(), world.snapshot())
            self.assertEqual(
                sorted(loaded.query(Position, Velocity)),
                sorted(world.query(Position, Velocity)),
            )


if __name__ == "__main__":
    unittest.main()
