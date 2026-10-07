# Local ECS Core

一个纯本地的 Entity Component System（ECS）核心，使用 Python 标准库实现。
所有 entity、component、system 和 world 状态只存在于**内存**或**本地 JSON 文件**中，
不依赖 Unity / Unreal / 游戏服务器 / 数据库或任何外部服务。

## 目录结构

```
ecs/
  __init__.py        # 包导出
  entity.py          # Entity 句柄（id + generation）
  errors.py          # 异常类型
  world.py           # World：生命周期、组件存储、query、system 调度、snapshot
  system.py          # System 基类
  command_buffer.py  # CommandBuffer：延迟结构性修改
tests/
  test_ecs.py        # 自动化测试（unittest，终端执行）
```

## 存储结构

- **Entity**：`Entity(id, generation)` 值对象。World 内部用平行数组
  `_generations` / `_alive` 管理槽位；销毁的槽位进入 free list 复用，
  复用时 generation 自增，因此旧的失效 handle 无法访问复用 ID 的新 entity。
- **Component**：`_components: dict[type, dict[int, component]]` —— 每种组件类型
  一张稀疏表，以 entity id 为键。一个 entity 对同一类型**至多一个**组件实例，
  从结构上杜绝不确定的重复状态；重复 `add_component` 会抛出
  `ComponentAlreadyExistsError`，需要替换时用 `set_component`（upsert）。

## Query 模型

`world.query(Position, Velocity)` 对各类型的稀疏表求交集，返回同时具有
所有指定组件的 `(entity, comp1, comp2, ...)` 元组，组件顺序与查询类型顺序一致。
结果集在迭代开始前**物化**，因此迭代期间新增/删除组件或销毁 entity
不会破坏当前遍历。

## 生命周期与 System

- `world.create_entity()` / `world.destroy_entity(e)` / `world.is_alive(e)`。
- System 通过 `world.add_system(sys)` 注册，`world.step(dt)` 严格按注册顺序执行。
- **CommandBuffer**：system 迭代中把结构性修改（创建/销毁 entity、增删组件）
  记录到 `CommandBuffer`，在安全的同步点调用 `world.flush(buf)` 统一回放。

## Snapshot

- `world.snapshot()` 返回可 JSON 序列化的 dict（generation、存活位、free list、
  全部组件数据）；`world.restore(snap)` / `World.from_snapshot(snap)` 恢复，
  恢复后 entity/component 状态与 query 结果与快照时完全一致。
- `world.save_snapshot(path)` / `World.load_snapshot(path)` 读写本地 JSON 文件。
- 组件类型通过 `world.register_component(T)` 或全局
  `ecs.register_component_type(T)` 注册以便反序列化。

## 运行测试

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖：entity 生命周期、ID 复用保护（stale handle）、组件增删改查与
重复禁止、多条件 query、迭代期间销毁/增删组件、system 顺序、
command buffer 延迟执行、snapshot 内存与文件往返恢复。

## 最小示例

```python
from dataclasses import dataclass
from ecs import System, World

@dataclass
class Position:
    x: float = 0.0
    y: float = 0.0

@dataclass
class Velocity:
    dx: float = 0.0
    dy: float = 0.0

class Movement(System):
    def update(self, world, dt):
        for _e, pos, vel in world.query(Position, Velocity):
            pos.x += vel.dx * dt
            pos.y += vel.dy * dt

world = World()
e = world.create_entity()
world.add_component(e, Position(0, 0))
world.add_component(e, Velocity(1, 1))
world.add_system(Movement())
world.step(dt=0.5)
print(world.get_component(e, Position))  # Position(x=0.5, y=0.5)
```
