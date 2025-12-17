# 战斗系统核心框架（完整说明文档）

> 本文档是基于当前代码实现生成的**完整 README / 设计文档**，用于说明：
> - 系统整体结构
> - 各核心类的职责与字段含义
> - 状态 / 资源 / 操作 / 元操作的设计思想
> - 可直接参考的定义与使用示例

---

## 目录

1. 设计目标与适用场景
2. 系统整体结构
3. Timer（时间系统）
4. Resource（资源系统）
5. State 与 StateManager（状态系统）
   - 5.1 状态计时模型
   - 5.2 StateResourceEffect（状态 ↔ 资源）
   - 5.3 meta_priority_rules（状态影响元操作优先级）
   - 5.4 OperationAccelerate（状态影响操作耗时）
6. StateEffect（状态影响资源消耗/产出）
7. Operation（操作 / 技能）
8. MetaOperation（元操作 / 连招）
9. Character（角色与循环构建）
10. 综合示例（状态 + 资源 + 操作 + 元操作）
11. 设计原则与注意事项

---

## 1. 设计目标与适用场景

该系统用于**描述并模拟战斗循环**，强调：

- 状态驱动（State-driven）
- 数据驱动（配置即逻辑）
- 可预测、可模拟（影子模拟）

适用于：

- 动作 / RPG / Roguelike 的技能与资源系统
- 数值验证与循环分析
- AI/自动策略选择（基于优先级）

---

## 2. 系统整体结构

```
Character
 ├── Timer                 全局时间轴
 ├── Resource              资源池（能量 / 热度 / 充能等）
 ├── StateManager           状态容器
 │    └── State             状态（叠层 / 计时 / 规则）
 ├── Operation              单次动作 / 技能
 └── MetaOperation          操作序列（连招 / 循环单元）
```

---

## 3. Timer（时间系统）

### 作用

- 作为整个系统的**唯一时间源**
- 所有状态过期、资源回复、操作耗时都基于它

### 核心字段

- `current_time`：当前时间
- `total_time`：可选，总战斗时长上限

### 核心方法

- `update(dt)`：时间前进 dt

---

## 4. Resource（资源系统）

### 定义

```python
Resource(id, upper_limit, current)
```

### 设计理念

- 所有可消耗数值都抽象为 Resource
- 不区分“主资源 / 次资源”，统一处理

### 字段说明

- `id`：资源标识
- `upper_limit`：最大值
- `current`：当前值
- `consume_total`：累计消耗量（统计/分析用）

### 行为

- `update(amount)`：
  - `amount < 0`：消耗（不足时报错）
  - `amount > 0`：恢复（自动 clamp 到上限）

---

## 5. State 与 StateManager（状态系统）

### State 的核心职责

- 表示**持续存在的条件**
- 可叠层、可过期
- 可在存在期间**影响其他系统**

### State 定义参数

- `id`：状态标识
- `current`：当前层数
- `upper_limit`：最大层数
- `time`：单层持续时间
- `type`：计时模型
- `length`：计时槽或持续时间

---

### 5.1 状态计时模型

#### type = 1（攻击保持模型）

- 任意一次 add 会刷新持续时间
- 超时后直接清空所有层数

#### type = 2（独立计时模型）

- 每一层单独计时
- 使用固定长度的 `start_time` 槽
- 层数会逐步减少

---

### 5.2 StateResourceEffect（状态 ↔ 资源）

用于：

- 过热时清空热度
- 进入状态时回复能量
- 状态结束时扣除资源

```python
StateResourceEffect(
  resource,
  on_add=0.0,
  on_remove=0.0,
  per_stack=False,
  ratio_on_add=None,
  ratio_on_remove=None
)
```

- `on_add / on_remove`：数值型修改
- `ratio_on_add / ratio_on_remove`：百分比设定（覆盖式）
- `per_stack=True`：按层数变化量生效

---

### 5.3 meta_priority_rules（状态影响元操作优先级）

```python
state.meta_priority_rules = [
  (meta_op, priority_delta)
]
```

规则：

- 只要状态存在（`current > 0`）就生效
- 自动叠加到 `MetaOperation.base_priority`
- 状态结束后自动恢复

无需显式回滚逻辑。

---

### 5.4 OperationAccelerate（状态影响操作耗时）

用于描述：

- 攻速加快
- 技能前摇缩短
- 多层状态逐层加速

```python
OperationAccelerate(
  operation,
  ratio=0.0,
  ratio_per_stack=0.0,
  by_current_stack=True,
  min_ratio=0.0,
  max_ratio=0.95
)
```

最终耗时计算：

```
effective_time = base_time * max(0, 1 - sum_ratio)
```

多个状态、多个规则可同时生效。

---

## 6. StateEffect（状态影响资源消耗 / 产出）

```python
StateEffect(
  state,
  target,      # consume / produce / both
  resource=None,
  op="mul",
  value=1.0,
  min_stack=1,
  max_stack=None
)
```

- 作用于 Operation 的资源结算阶段
- 支持 add / sub / mul / div
- 支持影子模拟（MetaOperation type=2）

---

## 7. Operation（操作 / 技能）

### 职责

- 表示一次**原子动作**
- 决定：
  - 消耗什么资源
  - 产生什么资源
  - 施加什么状态

### 核心能力

- 多资源消耗 / 产出
- 状态门槛（state_requirements）
- 禁止状态（state_forbids）
- 状态驱动耗时变化（OperationAccelerate）

### 核心方法

- `test()`：是否可释放
- `operate(timer, state_manager)`：执行
- `get_effective_time(state_manager)`：计算真实耗时

---

## 8. MetaOperation（元操作 / 连招）

### 定义

```python
MetaOperation(
  id,
  operations,
  type=1,
  meta_state_requirements=None,
  meta_state_forbids=None,
  base_priority=0
)
```

### 特点

- 表示固定操作序列
- 可作为 AI / 循环的决策单元

#### type = 1

- 线性判断：所有 op.test() 为 True 即可

#### type = 2

- 影子模拟：
  - 影子资源
  - 影子状态
  - 影子时间
- 可正确处理复杂依赖

---

## 9. Character（角色与循环构建）

### 角色持有内容

- Timer
- Resource 集合
- StateManager
- Operation 列表
- MetaOperation 列表

### 核心循环构建方式

#### build_rotation_from_meta()

- 动态计算 meta 优先级
- 从高到低选择第一个可执行的 meta

#### build_rotation_greedy_ops()

- 对单个 Operation 做贪心选择

---

## 10. 综合示例（简化版）

> 示例：肌肉记忆叠层 → 重攻加速 → 过热后解锁连招变体

```python
# 定义状态、操作、元操作后
log = character.build_rotation_from_meta(max_steps=10)
```

系统会自动完成：

- 状态叠层判断
- 操作耗时变化
- 元操作优先级切换

---

## 11. 设计原则与注意事项

1. **状态永远是被动的**
   - 状态不主动做事，只提供规则

2. **操作是唯一的执行者**
   - 所有资源 / 状态变化都通过 Operation 发生

3. **MetaOperation 只负责决策，不做数值修改**

4. **影子模拟必须与真实执行逻辑一致**
   - 当前实现已保证：耗时 / 状态 / 资源一致

5. **推荐使用 by_current_stack 的加速模型**
   - 避免层数变化顺序导致的不一致

---

> 该系统已具备：
> - 多状态依赖
> - 多资源联动
> - 加速 / 优先级 / 消耗的统一抽象
>
> 非常适合作为中大型技能系统的数值内核。
> 后续优化方向需要将伤害提升纳入优先级变化的考虑范畴