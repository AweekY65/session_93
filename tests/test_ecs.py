"""Terminal-runnable tests for the local ECS core (no game window needed)."""

from dataclasses import dataclass

import pytest

from ecs import (
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
    vx: float = 0.0
    vy: float = 0.0


@dataclass
class Health:
    hp: int = 100


COMPONENT_TYPES = {c.__name__: c for c in (Position, Velocity, Health)}


# ------------------------------------------------------------ entity lifecycle


class TestEntityLifecycle:
    def test_create_entities_have_unique_handles(self):
        world = World()
        a, b = world.create_entity(), world.create_entity()
        assert a != b
        assert world.is_alive(a) and world.is_alive(b)

    def test_destroy_entity(self):
        world = World()
        e = world.create_entity()
        world.destroy_entity(e)
        assert not world.is_alive(e)

    def test_double_destroy_raises(self):
        world = World()
        e = world.create_entity()
        world.destroy_entity(e)
        with pytest.raises(EntityNotAliveError):
            world.destroy_entity(e)

    def test_destroy_removes_all_components(self):
        world = World()
        e = world.create_entity()
        world.add_component(e, Position(1, 2))
        world.destroy_entity(e)
        assert list(world.query(Position)) == []


# ---------------------------------------------------------- id reuse protection


class TestIdReuseProtection:
    def test_recycled_index_gets_new_generation(self):
        world = World()
        old = world.create_entity()
        world.destroy_entity(old)
        new = world.create_entity()
        assert new.index == old.index  # index recycled
        assert new.generation != old.generation  # but handle differs

    def test_stale_handle_cannot_touch_new_entity(self):
        world = World()
        old = world.create_entity()
        world.destroy_entity(old)
        new = world.create_entity()
        world.add_component(new, Position(9, 9))

        assert not world.is_alive(old)
        with pytest.raises(EntityNotAliveError):
            world.get_component(old, Position)
        with pytest.raises(EntityNotAliveError):
            world.add_component(old, Velocity())
        with pytest.raises(EntityNotAliveError):
            world.remove_component(old, Position)
        with pytest.raises(EntityNotAliveError):
            world.destroy_entity(old)
        # New entity is unaffected.
        assert world.get_component(new, Position) == Position(9, 9)


# ---------------------------------------------------------- component operations


class TestComponentOperations:
    def test_add_read_modify_remove(self):
        world = World()
        e = world.create_entity()
        world.add_component(e, Position(1, 2))
        assert world.get_component(e, Position) == Position(1, 2)

        pos = world.get_component(e, Position)
        pos.x = 42
        assert world.get_component(e, Position).x == 42

        world.remove_component(e, Position)
        assert not world.has_component(e, Position)
        with pytest.raises(ComponentNotFoundError):
            world.get_component(e, Position)

    def test_duplicate_add_is_rejected(self):
        world = World()
        e = world.create_entity()
        world.add_component(e, Position(1, 1))
        with pytest.raises(ComponentAlreadyExistsError):
            world.add_component(e, Position(2, 2))
        # Original state is untouched: no ambiguous duplicate.
        assert world.get_component(e, Position) == Position(1, 1)

    def test_set_component_upserts(self):
        world = World()
        e = world.create_entity()
        world.set_component(e, Position(1, 1))
        world.set_component(e, Position(5, 5))
        assert world.get_component(e, Position) == Position(5, 5)

    def test_remove_missing_component_raises(self):
        world = World()
        e = world.create_entity()
        with pytest.raises(ComponentNotFoundError):
            world.remove_component(e, Velocity)

    def test_multiple_component_types_on_one_entity(self):
        world = World()
        e = world.create_entity()
        world.add_component(e, Position(1, 2))
        world.add_component(e, Velocity(3, 4))
        world.add_component(e, Health(80))
        assert world.get_component(e, Health).hp == 80
        assert world.has_component(e, Position)
        assert world.has_component(e, Velocity)


# ------------------------------------------------------------------------ query


class TestQuery:
    def _world_with_mix(self):
        world = World()
        both = world.create_entity()
        world.add_component(both, Position(1, 1))
        world.add_component(both, Velocity(1, 0))
        pos_only = world.create_entity()
        world.add_component(pos_only, Position(2, 2))
        vel_only = world.create_entity()
        world.add_component(vel_only, Velocity(0, 1))
        return world, both, pos_only, vel_only

    def test_query_requires_all_components(self):
        world, both, pos_only, vel_only = self._world_with_mix()
        results = list(world.query(Position, Velocity))
        assert [e for e, *_ in results] == [both]

        singles = {e for e, _ in world.query(Position)}
        assert singles == {both, pos_only}
        assert vel_only not in singles

    def test_query_yields_component_references(self):
        world, both, _, _ = self._world_with_mix()
        for entity, pos, vel in world.query(Position, Velocity):
            assert entity == both
            pos.x += vel.vx
        assert world.get_component(both, Position).x == 2

    def test_query_skips_destroyed_entities(self):
        world, both, _, _ = self._world_with_mix()
        world.destroy_entity(both)
        assert list(world.query(Position, Velocity)) == []

    def test_removal_during_iteration_does_not_corrupt_traversal(self):
        world = World()
        entities = []
        for i in range(5):
            e = world.create_entity()
            world.add_component(e, Position(i, i))
            world.add_component(e, Velocity(1, 1))
            entities.append(e)

        visited = []
        for entity, pos, vel in world.query(Position, Velocity):
            visited.append(entity)
            # Remove Velocity from the *next* entity mid-iteration.
            nxt = entities[entities.index(entity) + 1] if entity != entities[-1] else None
            if nxt is not None and world.has_component(nxt, Velocity):
                world.remove_component(nxt, Velocity)

        # Entities stripped of Velocity before being reached are skipped;
        # the iteration itself completes without error. Removing from the
        # next entity each step means even-indexed entities are visited.
        assert visited == [entities[0], entities[2], entities[4]]

    def test_destroy_during_iteration_is_safe(self):
        world = World()
        entities = []
        for i in range(4):
            e = world.create_entity()
            world.add_component(e, Position(i, i))
            entities.append(e)

        visited = []
        for entity, pos in world.query(Position):
            visited.append(entity)
            if entity == entities[0]:
                world.destroy_entity(entities[2])
        assert visited == [entities[0], entities[1], entities[3]]
        assert not world.is_alive(entities[2])


# ------------------------------------------------------------------ command buffer


class TestCommandBuffer:
    def test_commands_are_deferred_until_flush(self):
        world = World()
        e = world.create_entity()
        world.add_component(e, Position(1, 1))

        world.commands.add_component(e, Velocity(2, 2))
        world.commands.destroy_entity(e)
        # Nothing applied yet.
        assert world.is_alive(e)
        assert not world.has_component(e, Velocity)

        world.commands.flush()
        assert not world.is_alive(e)

    def test_update_flushes_commands_at_sync_point(self):
        world = World()
        e = world.create_entity()
        world.add_component(e, Position(0, 0))

        class Spawner(System):
            def update(self, w, dt):
                for entity, pos in w.query(Position):
                    # Structural change deferred: safe during iteration.
                    w.commands.add_component(entity, Velocity(1, 1))

        world.add_system(Spawner())
        world.update(0.016)
        assert world.has_component(e, Velocity)
        assert len(world.commands) == 0


# ------------------------------------------------------------------ system order


class TestSystemOrder:
    def test_systems_run_in_explicit_priority_order(self):
        world = World()
        calls = []

        class Recorder(System):
            def __init__(self, name):
                self.name = name

            def update(self, w, dt):
                calls.append(self.name)

        world.add_system(Recorder("third"), priority=20)
        world.add_system(Recorder("first"), priority=0)
        world.add_system(Recorder("second"), priority=10)
        world.update()
        assert calls == ["first", "second", "third"]

    def test_equal_priority_runs_in_registration_order(self):
        world = World()
        calls = []

        class Recorder(System):
            def __init__(self, name):
                self.name = name

            def update(self, w, dt):
                calls.append(self.name)

        world.add_system(Recorder("a"))
        world.add_system(Recorder("b"))
        world.update()
        assert calls == ["a", "b"]

    def test_movement_system_end_to_end(self):
        world = World()
        e = world.create_entity()
        world.add_component(e, Position(0, 0))
        world.add_component(e, Velocity(2, 3))

        class Movement(System):
            def update(self, w, dt):
                for entity, pos, vel in w.query(Position, Velocity):
                    pos.x += vel.vx * dt
                    pos.y += vel.vy * dt

        world.add_system(Movement())
        world.update(0.5)
        assert world.get_component(e, Position) == Position(1.0, 1.5)


# ---------------------------------------------------------------------- snapshot


class TestSnapshot:
    def _build_world(self):
        world = World()
        a = world.create_entity()
        world.add_component(a, Position(1, 2))
        world.add_component(a, Velocity(3, 4))
        b = world.create_entity()
        world.add_component(b, Position(5, 6))
        world.destroy_entity(b)  # leaves a free index + bumped generation
        c = world.create_entity()  # recycles b's index
        world.add_component(c, Health(50))
        return world, a, c, b

    def test_memory_snapshot_roundtrip(self):
        world, a, c, b = self._build_world()
        snap = world.snapshot()

        # Mutate the world after snapshotting.
        world.get_component(a, Position).x = 999
        world.destroy_entity(c)
        d = world.create_entity()
        world.add_component(d, Health(1))

        world.restore(snap, COMPONENT_TYPES)

        assert world.is_alive(a) and world.is_alive(c)
        assert world.get_component(a, Position) == Position(1, 2)
        assert world.get_component(a, Velocity) == Velocity(3, 4)
        assert world.get_component(c, Health) == Health(50)
        assert not world.is_alive(d)
        # Query results match the snapshot moment.
        assert [e for e, *_ in world.query(Position, Velocity)] == [a]
        assert [e for e, _ in world.query(Health)] == [c]
        # ID reuse protection state is restored too: the stale handle of
        # the long-destroyed b is still invalid, and c's recycled handle
        # (same index, newer generation) remains the valid one.
        assert not world.is_alive(b)
        assert b.index == c.index and b.generation != c.generation
        with pytest.raises(EntityNotAliveError):
            world.get_component(b, Health)

    def test_snapshot_is_deep(self):
        world, a, _, _ = self._build_world()
        snap = world.snapshot()
        world.get_component(a, Position).x = 12345
        world.restore(snap, COMPONENT_TYPES)
        assert world.get_component(a, Position).x == 1

    def test_file_snapshot_roundtrip(self, tmp_path):
        world, a, c, _ = self._build_world()
        path = tmp_path / "snapshot.json"
        world.save_snapshot(str(path))

        fresh = World()
        fresh.load_snapshot(str(path), COMPONENT_TYPES)

        assert fresh.is_alive(a) and fresh.is_alive(c)
        assert fresh.get_component(a, Position) == Position(1, 2)
        assert fresh.get_component(a, Velocity) == Velocity(3, 4)
        assert fresh.get_component(c, Health) == Health(50)
        assert [e for e, *_ in fresh.query(Position, Velocity)] == [a]
        assert [e for e, _ in fresh.query(Health)] == [c]
