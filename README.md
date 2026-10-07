# Local ECS Core

一个纯本地的 Entity Component System（ECS）核心，使用 Python 实现，无任何外部依赖。
所有 entity、component、system 与 world 状态只存在于**本地内存**中；snapshot 可
选地写入**本地 JSON 文件**。不依赖 Unity、Unreal、游戏服务器、数据库或任何外部服务。

## 目录结构

```
ecs/
  entity.py    # Entity 句柄：(index, generation)
  errors.py    # EntityNotAliveError / ComponentAlreadyExistsError / ...
  commands.py  # CommandBuffer：延迟结构性修改
  world.py     # World：生命周期、存储、query、system 调度、snapshot
  system.py    # System 基类
tests/
  test_ecs.py  # 全部自动化测试（终端运行，无需游戏窗口）
```

## 存储结构

- **Entity**：`Entity(index, generation)` 的不可变句柄。World 内部维护
  - `_generations: List[int]` —— 每个槽位当前的代数；
  - `_alive: Set[int]` —— 存活槽位集合；
  - `_free_indices: List[int]` —— 已销毁、可回收的槽位。
- **Component**：`Dict[component_type, Dict[entity_index, component]]`，
  即按组件类型分表的稀疏存储（sparse-set 的简化形态）。一个 entity 对同一
  类型最多持有一个组件实例。
- **System**：`(priority, 注册序号, system)` 列表，按优先级升序、同级按注册
  顺序排序，保证完全确定的执行顺序。

## 生命周期与 ID 复用保护

- `create_entity()`：优先复用 `_free_indices` 中的槽位，否则分配新槽位。
- `destroy_entity(e)`：移除该 entity 的全部组件，并将对应槽位的
  `generation + 1`。
- 旧句柄因为 generation 不匹配，`is_alive()` 返回 `False`，任何
  `get/add/remove/destroy` 操作都会抛出 `EntityNotAliveError` —— 即使该
  index 已被新 entity 复用，旧句柄也绝不会误访问新 entity。

## Component 操作

- `add_component(e, comp)`：挂载组件；同类型已存在时抛出
  `ComponentAlreadyExistsError`，**禁止不确定的重复状态**。
- `set_component(e, comp)`：upsert（存在则替换）。
- `get_component(e, T)` / `has_component(e, T)` / `remove_component(e, T)`：
  读取 / 判断 / 删除；读取或删除不存在的组件抛出 `ComponentNotFoundError`。

## Query 模型

`world.query(Position, Velocity)` 返回同时具有**所有**指定组件的 entity，
逐项 yield `(entity, comp1, comp2, ...)`，组件为可变引用，可直接修改。

迭代开始时先物化匹配列表，因此迭代期间的结构性修改不会破坏遍历：

- 迭代中新增 entity / 组件：本轮不可见；
- 迭代中移除某 entity 的必需组件或销毁它：轮到它时被跳过；
- 遍历本身永不因增删而崩溃或漏序。

## System 与 Command Buffer

- `world.add_system(system, priority=0)`：priority 小的先执行，同级按注册顺序。
- `world.update(dt)`：按确定顺序调用每个 system 的 `update(world, dt)`，
  随后在同一个 tick 末尾（安全同步点）执行 `world.commands.flush()`。
- `CommandBuffer` 支持 `create_entity / destroy_entity / add_component /
  remove_component / set_component`，把结构性修改延迟到同步点，system 在
  query 迭代中可以安全地记录命令。

## Snapshot

- `world.snapshot()` / `world.restore(snap, component_types)`：内存级深拷贝
  快照与恢复。
- `world.save_snapshot(path)` / `world.load_snapshot(path, component_types)`：
  本地 JSON 文件快照。`component_types` 为 `{类名: 类}` 映射，用于反序列化。
- 快照包含 generations、存活集合、空闲槽位与全部组件数据；恢复后 entity
  句柄有效性、组件状态与 query 结果与快照时刻完全一致（含 ID 复用保护状态）。

## 运行测试

```bash
cd <项目根目录>
python3 -m pytest -q
```

测试覆盖：entity 生命周期、ID 复用保护、component 增删改查与重复禁止、
多条件 query、迭代期间删除/销毁、command buffer 延迟执行、system 顺序、
内存与文件两种 snapshot 的保存/恢复一致性。全部在终端运行，无需游戏窗口。
