# ===================== Timer 类 =====================
from typing import Any


class Timer:
    """
    计时器类
    管理当前时间（单位由你自己决定：秒、帧、回合等）
    """
    def __init__(self, total_time=None):
        self.current_time = 0
        self.total_time = total_time  # 可选：总战斗时间上限

    def update(self, dt):
        """时间前进 dt"""
        self.current_time += dt
        return self.current_time

class StateResourceEffect:
    """
    状态 ↔ 资源 的一次性改动规则：
    - 当状态增加时：对某资源立刻加/减一定数量
    - 当状态减少/清空时：对某资源立刻加/减一定数量

    参数：
    - resource: Resource 对象
    - on_add: 状态增加时，每次触发的资源改变量（可为负）
    - on_remove: 状态减少/结束时，每次触发的资源改变量（可为负）
    - per_stack: True 表示按“层数变化量”乘以 on_add/on_remove；
                 False 表示只要触发一次就用 on_add/
    - ratio_on_add: 状态增加时，把资源设置为upper_limit * ratio_on_add
    - ratio_on_remove: 状态减少/结束时，把资源设置为upper_limit * ratio_on_remove
    """
    def __init__(self, resource, on_add=0.0, on_remove=0.0, per_stack=False, ratio_on_add=None, ratio_on_remove=None):
        self.resource = resource
        self.on_add = on_add
        self.on_remove = on_remove
        self.per_stack = per_stack
        self.ratio_on_add = ratio_on_add
        self.ratio_on_remove = ratio_on_remove


# ===================== State & StateManager =====================
class State:
    """
    状态类
    属性：
    1. id: 状态id
    2. current: 当前层数（或当前数量）
    3. upper_limit: 最大层数
    4. time: 单层持续时间（独立计时模型用）
    5. type: 状态类型
       1 = 攻击保持模型（类似“上一次攻击后 N 秒消失”）
       2 = 独立计时模型（每一层有自己的过期时间）
    6. length: 最大可同时存在的“计时槽”(对 type=2 有用)
    7. meta_priority_rules: 元操作优先级规则列表
        - 结构：[(meta_op, priority_delta), ...]
        - 默认：None 或 [] -> 不修改优先级
        - 状态存在时（current > 0）会对其中的 meta_op 优先级加上 priority_delta
        - 状态结束（current=0）后，优先级自动恢复为 base_priority。
    8. op_accelerate_rules: 状态存在时对操作生效的加速规则列表 [OperationAccelerate,...]
    """
    def __init__(self, id, current, upper_limit, time, type, length, resource_effects=None, meta_priority_rules=None, op_accelerate_rules=None, op_efficiency_rules=None):
        self.id = id
        self.current = current
        self.upper_limit = upper_limit
        self.time = time
        self.type = type
        self.length = length
        self.resource_effects = list(resource_effects) if resource_effects else []
        # 元操作优先级规则：
        # 结构：[(meta_op, priority_delta), ...]
        # - 默认：None 或 [] -> 不修改优先级
        # - 状态存在时（current > 0）会对其中的 meta_op 优先级加上 priority_delta
        self.meta_priority_rules = list(meta_priority_rules) if meta_priority_rules else []
        self.op_accelerate_rules = list(op_accelerate_rules) if op_accelerate_rules else []
        self.op_efficiency_rules = list(op_efficiency_rules) if op_efficiency_rules else []
        # type=1：只需要一个开始时间
        # type=2：每一层单独记录开始时间
        if self.type == 1:
            self.start_time = 0
        elif self.type == 2:
            # 固定长度的时间槽
            self.start_time = [None] * self.length
        else:
            raise ValueError("未知的状态类型，仅支持 1（攻击保持）和 2（独立计时）")

    def add(self, timer: Timer):
        prev = self.current

        if self.type == 1:
            self.current = min(self.upper_limit, self.current + 1)
            self.start_time = timer.current_time
        elif self.type == 2:
            self.start_time.sort(key = lambda x: float("inf") if x is None else x)
            self.start_time[0] = timer.current_time
            active = sum(1 for t in self.start_time if t is not None and timer.current_time - t <= self.time)
            self.current = min(self.upper_limit, active)

        gained = self.current - prev
        if gained > 0:
            self._apply_resource_on_gain(gained)


    def remove(self, timer: Timer):
        prev = self.current

        if self.type == 1:
            if timer.current_time - self.start_time > self.length:
                self.current = 0
                self.start_time = 0
        elif self.type == 2:
            active_count = 0
            for t in self.start_time:
                if t is None:
                    continue
                if timer.current_time - t <= self.time:
                    active_count += 1
            self.current = min(self.upper_limit, active_count)

        lost = prev - self.current
        if lost > 0:
            self._apply_resource_on_lose(lost)

    def force_clear(self):
        """
        立刻清空状态（不依赖时间），并触发一次“减少层数”的资源改动。
        用于 ResourceStateRemoveRule 或其他外部强制移除。
        """
        if self.current <= 0:
            # 清一下时间也行，看你需求
            if self.type == 1:
                self.start_time = 0
            elif self.type == 2:
                self.start_time = [None] * self.length
            return

        prev = self.current
        self.current = 0
        self._apply_resource_on_lose(prev)

        if self.type == 1:
            self.start_time = 0
        elif self.type == 2:
            self.start_time = [None] * self.length

    
    # ---------- 内部：根据层数变化，结算资源改动 ----------

    def _apply_resource_on_gain(self, delta_stack: int):
        """
        状态层数增加时调用。
        delta_stack: 本次增加的层数（可为 0 或正数）
        """
        if not self.resource_effects or delta_stack <= 0:
            return
        for eff in self.resource_effects:
            # 如果配置了ratio_on_add, 则优先按比例设置资源
            if eff.ratio_on_add is not None:
                target = eff.resource.upper_limit * eff.ratio_on_add
                delta = target - eff.resource.current
                if delta != 0:
                    eff.resource.update(delta)
                continue
            if eff.on_add == 0:
                continue
            amount = eff.on_add * (delta_stack if eff.per_stack else 1)
            if amount != 0:
                eff.resource.update(amount)

    def _apply_resource_on_lose(self, delta_stack: int):
        """
        状态层数减少/清空时调用。
        delta_stack: 本次减少的层数（可为 0 或正数）
        """
        if not self.resource_effects or delta_stack <= 0:
            return
        for eff in self.resource_effects:
            if eff.ratio_on_remove is not None:
                target = eff.resource.upper_limit * eff.ratio_on_remove
                delta = target - eff.resource.current
                if delta != 0:
                    eff.resource.update(delta)
                continue
            if eff.on_remove == 0:
                continue
            amount = eff.on_remove * (delta_stack if eff.per_stack else 1)
            if amount != 0:
                eff.resource.update(amount)


    def __repr__(self):
        return f"<State id={self.id}, current={self.current}, type={self.type}>"


class StateManager:
    """
    状态管理类：统一管理多个 State
    """
    def __init__(self, states=None):
        self.states = list(states) if states is not None else []

    def add_state(self, state: State):
        self.states.append(state)

    def update(self, timer: Timer):
        """每次行动前/后调用一次，用于移除过期状态"""
        for s in self.states:
            s.remove(timer)


# ===================== Resource 类 =====================
class Resource:
    """
    资源类，所有资源都需要继承这个类或直接使用这个类

    属性：
    1. id: 资源id
    2. upper_limit: 资源数量上限
    3. current: 当前数量
    4. consume_total: 累计消耗总量（可用于统计）
    """
    def __init__(self, id, upper_limit, current):
        self.id = id
        self.upper_limit = upper_limit
        self.current = current
        self.consume_total = 0

    def update(self, amount: float):
        """
        amount < 0: 消耗资源
        amount > 0: 获得资源（不超过上限）
        """
        if amount < 0:
            if self.current + amount < 0:
                raise ValueError(f"资源 {self.id} 数量不足")
            self.consume_total -= amount  # amount 是负数，实际消耗是 -amount
            self.current += amount
        elif amount > 0:
            self.current = min(self.upper_limit, self.current + amount)

    def __repr__(self):
        return f"<Resource id={self.id}, current={self.current}/{self.upper_limit}>"


class ResourceStateRule:
    """
    资源触发状态规则：
    当某个 Resource 达到/超过某个阈值时，自动给一个 State 加一层。

    参数：
    - resource: Resource 对象
    - threshold: 触发阈值，比如 100
    - state: 要添加的状态 State 对象
    - mode: 条件类型，默认为 ">="，也可以扩展为 "<=" 等
    - once: 是否只在“跨过阈值”的那一刻触发一次
            True  -> 从未满足 -> 满足（跨越阈值）时触发一次
            False -> 每次检测到条件满足就触发一次（可能叠很多层）
    """
    def __init__(self, resource, threshold, state, mode=">=", once=True):
        self.resource = resource
        self.threshold = threshold
        self.state = state
        self.mode = mode
        self.once = once
        self.was_active = False   # 用来检测“从未满足 -> 满足”的瞬间

    def _condition(self, value: float) -> bool:
        if self.mode == ">=":
            return value >= self.threshold
        elif self.mode == "<=":
            return value <= self.threshold
        else:
            raise ValueError(f"未知比较模式: {self.mode}")

    def check_and_apply(self, timer: Timer):
        """
        在资源更新之后调用：
        根据当前 resource.current 判断是否触发状态。
        """
        val = self.resource.current
        active = self._condition(val)

        if self.once:
            # 只在“第一次满足条件”的瞬间触发
            if active and not self.was_active:
                self.state.add(timer)
                self.was_active = True
            elif not active:
                # 条件不满足时重置，下次再跨过阈值还能再触发
                self.was_active = False
        else:
            # 只要条件满足，每次调用都触发（可能连续叠层）
            if active:
                self.state.add(timer)


class ResourceStateRemoveRule:
    """
    资源移除状态规则：
    当某个 Resource 满足某个条件时，直接把指定 State 清空（current=0）。

    典型用途：
    - 在 Overheat 状态下，如果 Rage 降到 0，则立刻移除 Overheat。
    - HP 降到 0 时移除某些增伤状态等。
    """

    def __init__(self, resource, state, threshold, mode="<=", require_active=True):
        """
        参数：
        - resource: Resource 对象
        - state: State 对象（要被移除的状态）
        - threshold: 阈值（比如 0）
        - mode: 比较方式，支持 "<=", ">=", "=="
        - require_active: 是否只在 state.current > 0 时才进行清除
        """
        self.resource = resource
        self.state = state
        self.threshold = threshold
        self.mode = mode
        self.require_active = require_active

    def _condition(self, value: float) -> bool:
        if self.mode == "<=":
            return value <= self.threshold
        elif self.mode == ">=":
            return value >= self.threshold
        elif self.mode == "==":
            return value == self.threshold
        else:
            raise ValueError(f"未知比较模式: {self.mode}")

    def check_and_apply(self):
        v = self.resource.current
        if not self._condition(v):
            return

        if self.require_active and self.state.current <= 0:
            return

        # 使用 State 自己的清空接口，保证资源改动被结算
        self.state.force_clear()



class ResourceRegenRule:
    """
    时间驱动的资源变化规则：
    每经过 dt 时间，对某个资源加/减 rate_per_sec * dt。

    参数：
    - resource: Resource 对象
    - rate_per_sec: 每秒变化量（可为负，表示衰减）
    - state_requirements: [(State, min_stack), ...] 只有在这些状态满足时才生效（可选）
    - state_forbids: [State, ...] 如果这些状态存在则不生效（可选）
    """
    def __init__(self, resource, rate_per_sec,
                 state_requirements=None, state_forbids=None):
        self.resource = resource
        self.rate_per_sec = rate_per_sec
        self.state_requirements = list(state_requirements) if state_requirements else []
        self.state_forbids = list(state_forbids) if state_forbids else []

    def _check_states(self):
        # 状态门槛
        for st, need in self.state_requirements:
            if st.current < need:
                return False
        for st in self.state_forbids:
            if st.current > 0:
                return False
        return True

    def apply(self, dt: float):
        """
        在时间前进 dt 之后调用：
        如果状态条件满足，为 resource 增加 rate_per_sec * dt。
        """
        if not self._check_states():
            return
        if dt <= 0:
            return
        amount = self.rate_per_sec * dt
        if amount != 0:
            self.resource.update(amount)

class OperationAccelerate:
    """
    操作加速规则（由 State 持有）：

    - operation: 要被加速的 Operation 对象

    三种写法（任选其一）：
    1) 固定加速：ratio
       ratio=0.2 -> 时间缩短 20%，effective_time = base_time*(1-0.2)

    2) 每层加速：ratio_per_stack * stack
       ratio_per_stack=0.05，且按“变化层数”生效（per_stack=True）
       -> 每增加1层，加速+5%；每掉1层，加速-5%

    3) 按当前层数计算：ratio_per_stack * current_stack
       by_current_stack=True
       -> 每次计算时用 state.current 动态决定（最简单也最不容易出错）
    """
    def __init__(
        self,
        operation,
        *,
        ratio: float = 0.0,
        ratio_per_stack: float = 0.0,
        by_current_stack: bool = True,
        state_ref=None,  # 可选：显式指定关联的 State（如果不传，会由调用方传入）
        min_ratio: float = 0.0,
        max_ratio: float = 0.95,
    ):
        self.operation = operation
        self.ratio = ratio
        self.ratio_per_stack = ratio_per_stack
        self.by_current_stack = by_current_stack
        self.state_ref = state_ref
        self.min_ratio = min_ratio
        self.max_ratio = max_ratio



class StateEffect:
    """
    状态修正规则：
    在特定状态存在时，修改本 Operation 的资源消耗或产出数量。

    参数：
    - state: State 对象（检查 state.current）
    - target: "consume" / "produce" / "both"
    - resource: 受影响的 Resource 对象，或 None 表示作用于所有资源
    - op: "add" / "sub" / "mul" / "div"
    - value: 运算值
    - min_stack: 状态层数至少达到多少才生效
    - max_stack: 状态层数超过多少则不再生效（可选）
    """

    def __init__(
        self,
        state,
        target,
        resource=None,
        op="mul",
        value=1.0,
        min_stack=1,
        max_stack=None
    ):
        self.state = state
        self.target = target  # "consume" / "produce" / "both"
        self.resource = resource  # Resource 或 None
        self.op = op
        self.value = value
        self.min_stack = min_stack
        self.max_stack = max_stack

    def _active(self, state_override=None):
        """
        判断状态是否满足层数要求。
        state_override: 可选映射 { 原始State对象 : 影子State对象 }
                        若提供，则使用影子State.current，否则使用真实State.current
        """
        if state_override is not None and self.state in state_override:
            cur = state_override[self.state].current
        else:
            cur = self.state.current

        if cur < self.min_stack:
            return False
        if self.max_stack is not None and cur > self.max_stack:
            return False
        return True

    def apply_to_amount(self, res, amount, target_kind: str, state_override=None) -> float:
        """
        对单个资源 amount 应用修正。
        target_kind: "consume" 或 "produce"
        state_override: 可选映射 { 原始State : 影子State }，用于影子模拟。
        """
        # 目标类型不匹配，直接跳过
        if self.target not in ("both", target_kind):
            return amount

        # 状态层数不满足
        if not self._active(state_override=state_override):
            return amount

        # 限定某个资源时，检查资源是否匹配
        if self.resource is not None and self.resource is not res:
            return amount

        # 执行运算
        op = self.op
        v = self.value

        try:
            if op == "add":
                amount = amount + v
            elif op == "sub":
                amount = amount - v
            elif op == "mul":
                amount = amount * v
            elif op == "div":
                if v != 0:
                    amount = amount / v
                # v == 0 时，保持原值，避免报错
        except Exception:
            # 出任何意外都保持原值，避免中断
            pass

        return amount




# ===================== Operation 类 =====================
class Operation:
    """
    操作类，所有具体技能/操作可以继承这个类，或者直接配置这个类实例

    属性：
    1. id: 操作名/操作id
    2. time: 操作耗时
    3. resource_requirements: 主资源需求列表（比如“体力”、“能量”，决定能不能发动）
    4. resource_outputs: 产出资源列表 [Resource, Resource, ...]
    5. resource_consumes: 单次基础消耗列表 [float, float, ...]，与 resource_requirements 一一对应
    6. resource_produces: 产出数量列表，对应 resource_outputs [float, float, ...]
    7. consume_upper_limit / consume_lower_limit: 单次资源消耗上下限（对每个依赖资源都适用）
    8. statesoutput: 本操作会施加的状态列表 [State, State,...]
    9. resource_state_rules: 资源到达某值时触发状态的规则列表 [ResourceStateRule,...]
    10. state_requirements: 状态需求列表 [(State, min_stack), ...]，满足才可释放
    11. state_forbids: 禁止状态列表 [State,...]，若当前有该状态（current > 0）则无法释放
    """

    def __init__(
        self,
        id,
        time,
        resource_requirements,
        resource_outputs,
        resource_consumes,
        resource_produces,
        consume_upper_limit,
        consume_lower_limit,
        statesoutput,
        resource_state_rules=None,
        state_requirements=None,   # ✅ 新增：需要的状态
        state_forbids=None,         # ✅ 新增：禁止的状态
        resource_state_remove_rules=None,
        state_effects=None,
    ):
        # 基本信息
        self.id = id
        self.time = time
        self.base_time = time # 记录基础耗时，后续加速再这个基础上算

        # 多资源依赖
        self.resource_requirements = list(resource_requirements)
        self.resource_outputs = list(resource_outputs)

        self.resource_consumes = list(resource_consumes)
        self.resource_produces = list(resource_produces)

        assert len(self.resource_requirements) == len(self.resource_consumes), \
            "resource_requirements 和 resource_consumes 长度必须一致"
        assert len(self.resource_outputs) == len(self.resource_produces), \
            "resource_outputs 和 resource_produces 长度必须一致"

        # 消耗上下限（对每个资源都适用）
        self.consume_upper_limit = consume_upper_limit
        self.consume_lower_limit = consume_lower_limit

        # 直接施加的状态
        self.statesoutput = list(statesoutput)

        # 资源→状态 规则
        self.resource_state_rules = list(resource_state_rules) if resource_state_rules else []

        # ✅ 状态条件（可选）
        # 需要的状态：[(State, min_stack), ...]
        self.state_requirements = list(state_requirements) if state_requirements else []
        # 禁止的状态：[State, ...]
        self.state_forbids = list(state_forbids) if state_forbids else []
        
        # 资源→状态 移除规则
        self.resource_state_remove_rules = list(resource_state_remove_rules) if resource_state_remove_rules else []

        # 状态影响资源操作的资源消耗/产出的规则
        self.state_effects = list(state_effects) if state_effects else []

        # 统计
        self.counter = 0  # 该操作被执行次数


        # ---------- 内部：对某一类资源数量应用 state_effects ----------
    def _apply_state_effects_to_map(self, amount_map, target_kind: str, state_override=None):
        """
        amount_map: dict { Resource对象 : 数量 }
        target_kind: "consume" 或 "produce"

        返回：新的 amount_map（会生成一个新的 dict，不在原地修改）
        """
        if not self.state_effects:
            return amount_map

        new_map = {}
        for res, base_amt in amount_map.items():
            amt = base_amt
            for eff in self.state_effects:
                amt = eff.apply_to_amount(res, amt, target_kind, state_override=state_override)
            new_map[res] = amt
        return new_map
    

    def _apply_op_efficiency_rules(self, amount_map: dict, target_kind: str, state_manager=None):
        """
        amount_map: {Resource: amount}
        target_kind: "consume" or "produce"
        state_manager: 用于读取当前状态与层数
        """
        if state_manager is None:
            return amount_map

        new_map = dict(amount_map)

        for st in state_manager.states:
            if st.current <= 0:
                continue
            rules = getattr(st, "op_efficiency_rules", None)
            if not rules:
                continue

            for rule in rules:
                if rule.operation is not self:
                    continue
                if rule.target not in ("both", target_kind):
                    continue

                # 计算 effective_mul（可按层数）
                m = float(getattr(rule, "mul", 1.0) or 1.0)
                mps = float(getattr(rule, "mul_per_stack", 0.0) or 0.0)
                if mps != 0.0 and getattr(rule, "by_current_stack", True):
                    m = m + mps * st.current

                mn = float(getattr(rule, "min_mul", 0.0))
                mx = float(getattr(rule, "max_mul", 10.0))
                if m < mn: m = mn
                if m > mx: m = mx

                # 应用到指定资源 or 全部资源
                if getattr(rule, "resource", None) is None:
                    for res in list(new_map.keys()):
                        new_map[res] = new_map[res] * m
                else:
                    res = rule.resource
                    if res in new_map:
                        new_map[res] = new_map[res] * m

        return new_map

    # ---------- 内部：计算每种资源的实际消耗 ----------

    def _calc_consume_amounts(self, state_override=None, state_manager=None):
        """
        返回：
            consume_map: dict { Resource对象 : 理论消耗量 }

        不考虑当前资源，只考虑配置 + 状态修正。
        """
        raw_map = {}
        for res, base in zip(self.resource_requirements, self.resource_consumes):
            c = base
            if self.consume_upper_limit is not None:
                c = min(c, self.consume_upper_limit)
            if self.consume_lower_limit is not None:
                c = max(c, self.consume_lower_limit)
            raw_map[res] = c

        # 状态对消耗做修正（可能加减乘除）
        modified_map = self._apply_state_effects_to_map(
            raw_map, target_kind="consume", state_override=state_override
        )
        modified_map = self._apply_op_efficiency_rules(modified_map, target_kind="consume", state_manager=state_manager)

        consume_map = {}
        for res, amt in modified_map.items():
            if amt < 0:
                amt = 0
            if self.consume_upper_limit is not None:
                amt = min(amt, self.consume_upper_limit)
            consume_map[res] = amt

        return consume_map
    
    def _calc_produce_amounts(self, state_override=None, state_manager=None):
        """
        计算每种资源的“理论产出量”（不考虑当前值，只考虑：
        - 基础配置 resource_produces
        - state_effects 修正
        返回：
            produce_map: dict { Resource对象 : 理论产出量 }（可能为 0 或正数）
        """
        raw_map = {}
        for out_res, base_prod in zip(self.resource_outputs, self.resource_produces):
            raw_map[out_res] = base_prod

        produce_map = self._apply_state_effects_to_map(raw_map, target_kind="produce", state_override=state_override)
        produce_map = self._apply_op_efficiency_rules(produce_map, target_kind="produce", state_manager=state_manager)
        # 这里不做上限 clamp，上限在真正更新或模拟更新时处理
        return produce_map

    def get_effective_time(self, state_manager: "StateManager" = None) -> float:
        """
        根据当前状态，计算本次操作的“实际耗时”：
        - 默认：返回 base_time
        - 若有状态存在，且其 op_accelerate_rules 中包含针对本 Operation 的规则，
          则累加所有 ratio，最终：
              effective_time = base_time * max(0, 1 - sum_ratio)
        """
        base_time = getattr(self, "base_time", self.time)

        if state_manager is None:
            return base_time

        total_ratio = 0.0
        for st in state_manager.states:
            if st.current <= 0:
                continue
            rules = getattr(st, "op_accelerate_rules", None)
            if not rules:
                continue

            for acc in rules:
                if acc.operation is not self:
                    continue

                # 1) 固定 ratio
                r = float(getattr(acc, "ratio", 0.0) or 0.0)
                # 2) 层数相关
                rps = float(getattr(acc, "ratio_per_stack", 0.0) or 0.0)
                if rps != 0.0:
                    # 默认按当前层数动态决定
                    if getattr(acc, "by_current_stack", True):
                        stack = st.current
                        r += rps * stack
                # clamp
                mn = float(getattr(acc, "min_ratio", 0.0))
                mx = float(getattr(acc, "max_ratio", 0.95))
                if r < mn:
                    r = mn
                if r > mx:
                    r = mx
                total_ratio += r

        factor = 1.0 - total_ratio
        if factor < 0.0:
            factor = 0.0  # 防止变成负时间，你也可以在这里设一个最小值

        return base_time * factor


    # ---------- 内部：状态合法性检查 ----------
    def _check_state_conditions(self):
        """
        检查状态是否满足释放条件：
        - 所有 state_requirements: state.current >= min_stack
        - 所有 state_forbids: state.current == 0
        """
        # 必须存在的状态
        for st, need in self.state_requirements:
            if st.current < need:
                return False

        # 禁止存在的状态
        for st in self.state_forbids:
            if st.current > 0:
                return False

        return True

    def _check_state_conditions_shadow(self, shadow_state_map):
        """
        使用影子 State 检查状态条件。
        shadow_state_map: { 原始State : 影子State }
        """
        for st, need in self.state_requirements:
            cur = shadow_state_map[st].current
            if cur < need:
                return False
        for st in self.state_forbids:
            cur = shadow_state_map[st].current
            if cur > 0:
                return False
        return True

    # ---------- 综合合法性：资源 + 状态 ----------
    def test(self, state_manager=None):
        """
        返回当前时刻该技能是否可以释放：
        - 状态条件不满足 ⇒ False
        - 任意一个资源的“理论消耗量” > 当前值 ⇒ False
        """
        if not self._check_state_conditions():
            return False

        consume_map = self._calc_consume_amounts(state_manager=state_manager)

        # 资源不足就放不出技能
        for res, need in consume_map.items():
            if need > res.current:
                return False

        return True

    def operate(self, timer: Timer, state_manager: StateManager = None):
        """
        执行一次操作：

        返回：
            [操作id, 已执行次数, 当前时间, 消耗信息{res_id: consume}]
        """
        if not self.test(state_manager=state_manager):
            raise ValueError(f"资源或状态条件不足，无法执行操作 {self.id}")

        self.counter += 1

        # 1. 资源消耗
        consume_map = self._calc_consume_amounts(state_manager=state_manager)
        for res, c in consume_map.items():
            # 为安全起见再 check 一下
            if c > res.current:
                raise ValueError(f"执行 {self.id} 时资源 {res.id} 不足（需要 {c}，当前 {res.current}）")
            res.update(-c)

        # 2. 资源产出
        produce_map = self._calc_produce_amounts(state_manager=state_manager)
        for out_res, amt in produce_map.items():
            if amt <= 0:
                continue
            out_res.update(amt)

        # 3. 资源→状态 规则触发（真实执行）
        for rule in self.resource_state_rules:
            rule.check_and_apply(timer)

        for rule in self.resource_state_remove_rules:
            rule.check_and_apply()

        # 4. 时间推进
        if state_manager is not None:
            dt = self.get_effective_time(state_manager)
        else:
            dt = getattr(self, "base_time", self.time)
        timer.update(dt)

        # 5. 本操作直接施加的状态
        for st in self.statesoutput:
            st.add(timer)

        consume_by_id = {res.id: c for res, c in consume_map.items()}
        return [self.id, self.counter, timer.current_time, consume_by_id]

    def __repr__(self):
        return f"<Operation id={self.id}>"

# ===================== MetaOperation（元操作） =====================
class MetaOperation:
    """
    元操作：由若干 Operation 构成的固定序列
    - type=1: 线性资源，检测简单（所有 op.test() 为 True 即可）
    - type=2: 非线性资源，使用“影子资源 + 影子状态 + 影子时间”完整模拟
    - meta_state_requirements: [(State, min_stack), ...] 只有满足这些状态时，这个元操作才会进入候选列表
    - meta_state_forbids: [State, ...] 如果这些状态存在，则禁用这个元操作
    - base_priority: 基础优先级（整数，越大越优先）
    """

    def __init__(self, id, operations, type=1, meta_state_requirements=None, meta_state_forbids=None, base_priority=0):
        self.id = id
        self.operations = list(operations)
        self.type = type
        self.meta_state_requirements = list(meta_state_requirements) if meta_state_requirements else []
        self.meta_state_forbids = list(meta_state_forbids) if meta_state_forbids else []
        self.base_priority = base_priority
    
    def _check_meta_state_conditions(self, state_manager: StateManager):
        """
        使用当前 state_manager 里的真实 State 检查：
        - meta_state_requirements: state.current >= min_stack
        - meta_state_forbids: state.current == 0
        """
        if state_manager is None:
            # 如果你不想让 meta 依赖状态，可以不传 state_manager
            return True
        for st, need in self.meta_state_requirements:
            if st.current < need:
                return False

        for st in self.meta_state_forbids:
            if st.current > 0:
                return False
        return True
    
    def get_priority(self, state_manager: StateManager = None):
        """
        计算当前状态下，这个元操作的优先级。
        如果返回 None，表示当前状态下这个元操作“完全不在候选列表里”。

        优先级规则：
        1）先判断 meta_state_requirements / meta_state_forbids 是否允许这个元操作启用；
        2）默认优先级 = base_priority；
        3）遍历所有 State：
           - 若 state.current > 0 且 state.meta_priority_rules 中包含 (self, delta)，
             则在 base_priority 基础上累加 delta。
        4）不区分时机，只要状态存在，优先级就变化；
           状态结束（current=0）后，优先级自动恢复为 base_priority。
        """
        # 1）先看这个 MetaOperation 在当前状态下是否启用
        if not self._check_meta_state_conditions(state_manager):
            return None

        # 2）默认优先级：base_priority
        priority = self.base_priority

        # 3）叠加“状态对元操作优先级的修正”
        if state_manager is not None:
            for st in state_manager.states:
                if st.current <= 0:
                    continue
                if not getattr(st, "meta_priority_rules", None):
                    continue

                for meta_op, delta in st.meta_priority_rules:
                    if meta_op is self:
                        priority += delta

        return priority


    def _build_shadow_states(self, state_manager: StateManager):
        """
        从当前 StateManager 和所有 Operation 中，构建“原始State -> 影子State”的映射，
        并返回影子 StateManager。
        """
        shadow_map = {}

        # 1）先把 state_manager 中的状态都拷一份
        for st in state_manager.states:
            shadow = State(
                st.id, 
                st.current, 
                st.upper_limit, 
                st.time, st.type, 
                st.length, 
                resource_effects = None, 
                meta_priority_rules = list(st.meta_priority_rules),
                op_accelerate_rules = list(getattr(st, "op_accelerate_rules", [])),
                op_efficiency_rules = list(getattr(st, "op_efficiency_rules", [])),)
            # 拷贝 start_time（保持相对时间关系）
            if st.type == 1:
                shadow.start_time = st.start_time
            elif st.type == 2:
                shadow.start_time = list(st.start_time)
            shadow_map[st] = shadow

        # 2）确保所有 Operation 用到的 State 都有影子
        def ensure_shadow(st: State):
            if st in shadow_map:
                return
            shadow = State(
                st.id, 
                st.current, 
                st.upper_limit, 
                st.time, 
                st.type, 
                st.length,
                resource_effects = None,
                meta_priority_rules = list(st.meta_priority_rules),
                op_accelerate_rules = list(getattr(st, "op_accelerate_rules", [])),
                op_efficiency_rules = list(getattr(st, "op_efficiency_rules", [])),)
            if st.type == 1:
                shadow.start_time = st.start_time
            elif st.type == 2:
                shadow.start_time = list(st.start_time)
            shadow_map[st] = shadow

        for op in self.operations:
            for st, _ in op.state_requirements:
                ensure_shadow(st)
            for st in op.state_forbids:
                ensure_shadow(st)
            for eff in op.state_effects:
                ensure_shadow(eff.state)
            for st in op.statesoutput:
                ensure_shadow(st)

        shadow_manager = StateManager(list(shadow_map.values()))
        return shadow_map, shadow_manager

    def _simulate_full(self, timer: Timer, state_manager: StateManager):
        """
        使用影子 Resource / Timer / State 来完整模拟整个元操作：
        - 状态条件用影子State判断
        - 消耗/产出用影子State参与的 state_effects 计算
        - 资源在 temp 上扣/加
        - 时间用影子 Timer 推进并驱动影子 StateManager 过期
        - 直接施加状态 (statesoutput) 作用在影子State上

        不会修改真实 Resource / State / Timer。
        """

        # ---------- 影子资源 ----------
        temp = {}
        for op in self.operations:
            for res in op.resource_requirements:
                if res not in temp:
                    temp[res] = [res.current, res.upper_limit]
            for out in op.resource_outputs:
                if out not in temp:
                    temp[out] = [out.current, out.upper_limit]

        # ---------- 影子状态 ----------
        shadow_state_map, shadow_state_manager = self._build_shadow_states(state_manager)

        # ---------- 影子时间 ----------
        shadow_timer = Timer(total_time=timer.total_time)
        shadow_timer.current_time = timer.current_time

        # ---------- 按顺序模拟每个 Operation ----------
        for op in self.operations:
            # 1. 用影子状态检查状态条件
            if not op._check_state_conditions_shadow(shadow_state_map):
                return False

            # 2. 资源门槛：至少要 >= consume_lower_limit（如果有）
            if op.consume_lower_limit is not None:
                for res in op.resource_requirements:
                    cur, lim = temp[res]
                    if cur < op.consume_lower_limit:
                        return False

            # 3. 计算理论消耗量（使用影子状态参与 state_effects）
            consume_map = op._calc_consume_amounts(state_override=shadow_state_map, state_manager=shadow_state_manager)

            # 扣除资源：任一步 cur < need ⇒ 整个失败
            for res, need in consume_map.items():
                cur, lim = temp[res]
                if cur < need:
                    return False
                temp[res][0] = cur - need

            # 4. 模拟资源产出
            produce_map = op._calc_produce_amounts(state_override=shadow_state_map, state_manager=shadow_state_manager)
            for out_res, amount in produce_map.items():
                if amount <= 0:
                    continue
                cur, lim = temp[out_res]
                cur = min(lim, cur + amount)
                temp[out_res][0] = cur

            # 5. 推进影子时间 & 状态过期
            eff_time = op.get_effective_time(shadow_state_manager)
            shadow_timer.update(eff_time)
            shadow_state_manager.update(shadow_timer)

            # 6. 本操作直接施加的状态，作用在影子状态上
            for st in op.statesoutput:
                shadow_state_map[st].add(shadow_timer)

        return True

    def can_execute(self, timer: Timer = None, state_manager: StateManager = None):
        """
        当前资源 + 状态 下，是否可以完整执行整个元操作。
        type=1：直接 all(op.test())
        type=2：需要 timer 和 state_manager，用影子完整模拟。
        """
        if not self._check_meta_state_conditions(state_manager):
            return False

        if self.type == 1:
            return all(op.test(state_manager=state_manager) for op in self.operations)

        elif self.type == 2:
            if timer is None or state_manager is None:
                raise ValueError("MetaOperation(type=2).can_execute() 需要提供 timer 和 state_manager")
            return self._simulate_full(timer, state_manager)

        else:
            raise ValueError("MetaOperation.type 只能为 1 或 2")

    def execute(self, timer: Timer, state_manager: StateManager = None, record_list=None, character = None):
        """
        真正执行整个元操作。
        """
        if not self.can_execute(timer, state_manager):
            raise ValueError(f"当前资源或状态不足，无法发动元操作 {self.id}")

        if record_list is None:
            record_list = []

        for op in self.operations:
            rec = op.operate(timer, state_manager)
            record_list.append(rec)
            if character is not None:
                character._after_operation_executed(op)
            if state_manager is not None:
                state_manager.update(timer)

        return record_list

    def __repr__(self):
        return f"<MetaOperation id={self.id}, type={self.type}, ops={len(self.operations)}>"


class ResourceThreshold:
    def __init__(self, resource: Resource, threshold: float, mode: str = ">="):
        self.resource = resource
        self.threshold = threshold
        self.mode = mode

    def check(self) -> bool:
        v = self.resource.current
        if self.mode == ">=":
            return v >= self.threshold
        if self.mode == "<=":
            return v <= self.threshold
        if self.mode == "==":
            return v == self.threshold
        raise ValueError(f"Unknown mode: {self.mode}")


class OperationTriggeredStateRule:
    """
    当“执行某个 Operation”时，检查 AND 条件：
    - 必须处于 required_states（每个满足 min_stack）
    - 必须不处于 forbidden_states
    - 必须满足 resource_thresholds
    满足则对 target_state add()（或 add 多层）
    """
    def __init__(
        self,
        *,
        trigger_operation: Operation,          # x
        target_state: State,                   # b
        required_states=None,                  # [(a,1),(c,1)]
        forbidden_states=None,                 # [d,...] 可选
        resource_thresholds=None,              # [ResourceThreshold(y,n,">="), ...]
        add_stacks: int = 1,                   # 满足后给 b 加几层
        once_per_operation_call: bool = True,  # 预留：未来多次触发控制
    ):
        self.trigger_operation = trigger_operation
        self.target_state = target_state
        self.required_states = list(required_states) if required_states else []
        self.forbidden_states = list(forbidden_states) if forbidden_states else []
        self.resource_thresholds = list(resource_thresholds) if resource_thresholds else []
        self.add_stacks = add_stacks
        self.once_per_operation_call = once_per_operation_call

    def _check_states(self) -> bool:
        for st, need in self.required_states:
            if st.current < need:
                return False
        for st in self.forbidden_states:
            if st.current > 0:
                return False
        return True

    def _check_resources(self) -> bool:
        for th in self.resource_thresholds:
            if not th.check():
                return False
        return True

    def try_apply(self, executed_op: Operation, timer: Timer):
        # 必须是指定操作触发
        if executed_op is not self.trigger_operation:
            return

        # AND 条件
        if not self._check_states():
            return
        if not self._check_resources():
            return

        # 触发：加 b 状态
        for _ in range(max(0, int(self.add_stacks))):
            self.target_state.add(timer)

class OperationResourceEfficiency:
    """
    状态对“某个 Operation 的资源消耗/获取效率”修正规则（由 State 持有）。

    典型用途：
    - 让 opX 的能量消耗 *0.8（省能）
    - 让 opX 的热能获取 *1.25（增产）
    - 按层数线性叠加：每层消耗再 *0.95 / 产出再 *1.05

    参数：
    - operation: 目标 Operation
    - target: "consume" / "produce" / "both"
    - resource: 指定某个 Resource；None 表示对该 Operation 的所有资源生效
    - mul: 基础乘法系数（1.0 表示不变）
    - mul_per_stack: 每层额外乘法系数增量（线性叠加到 mul 上）
        例如 mul=1.0, mul_per_stack=-0.05, stack=3 -> effective_mul = 1.0 + (-0.05)*3 = 0.85
    - by_current_stack: True 则实时按 state.current 计算（推荐）
    - min_mul/max_mul: clamp，避免出现负数或过大
    """
    def __init__(
        self,
        operation,
        *,
        target: str = "both",
        resource=None,
        mul: float = 1.0,
        mul_per_stack: float = 0.0,
        by_current_stack: bool = True,
        min_mul: float = 0.0,
        max_mul: float = 10.0,
    ):
        self.operation = operation
        self.target = target
        self.resource = resource
        self.mul = mul
        self.mul_per_stack = mul_per_stack
        self.by_current_stack = by_current_stack
        self.min_mul = min_mul
        self.max_mul = max_mul





# ===================== Character（角色） =====================
class Character:
    """
    角色类：管理角色拥有的资源、状态、操作和元操作，并提供两种操作生成逻辑。

    属性：
    1. name: 角色名
    2. timer: Timer
    3. resources: {id: Resource}
    4. state_manager: StateManager
    5. operations: [Operation, ...] 可选，单个操作优先级用
    6. meta_operations: [MetaOperation, ...] 可选，按列表顺序作为优先级
    """

    def __init__(self, name, timer: Timer, resources=None, states=None):
        self.name = name
        self.timer = timer
        self.resources = {} if resources is None else {r.id: r for r in resources}
        self.state_manager = StateManager(states or [])
        self.operations = []        # 单个操作列表
        self.meta_operations = []   # 元操作列表（优先级 = 列表顺序）
        self.resource_regen_rules = []
        self._last_tick_time = self.timer.current_time
        self.op_triggered_state_rules = []
    
    def add_op_trigger_rule(self, rule: OperationTriggeredStateRule):
        self.op_triggered_state_rules.append(rule)   
    
    def _after_operation_executed(self, op: Operation):
        # 在操作执行成功后触发规则
        for rule in self.op_triggered_state_rules:
            rule.try_apply(op, self.timer)
        self.state_manager.update(self.timer)

    def add_resource(self, res: Resource):
        self.resources[res.id] = res

    def add_state(self, st: State):
        self.state_manager.add_state(st)

    def add_operation(self, op: Operation):
        self.operations.append(op)

    def add_meta_operation(self, mop: MetaOperation):
        self.meta_operations.append(mop)
    
    def add_regen_rule(self, rule: ResourceRegenRule):
        """为角色添加一个“随时间变化资源”的规则"""
        self.resource_regen_rules.append(rule)

    def _apply_time_regen(self):
        """
        根据 timer.current_time 与上次结算时间差，结算随时间变化的资源。
        设计成内部函数，只在 build_rotation_* 中调用。
        """
        now = self.timer.current_time
        dt = now - self._last_tick_time
        if dt <= 0:
            return
        for rule in self.resource_regen_rules:
            rule.apply(dt)
        self._last_tick_time = now

    # ---------- 逻辑 1：基于元操作的循环 ----------

    def build_rotation_from_meta(self, max_steps=9999):
        """
        逻辑1：
        按“当前状态决定的优先级”来选择元操作：
          1）根据 state_manager 计算每个 MetaOperation 的优先级（get_priority）
          2）过滤掉当前状态下不启用的 meta（priority is None）
          3）按优先级从高到低，找第一个 can_execute 的元操作执行
        重复上述过程，直到所有元操作都无法执行，或达到 max_steps 次元操作。
        """
        rotation_log = []
        steps = 0

        while steps < max_steps:
            # 先结算一次状态过期
            self.state_manager.update(self.timer)

            # 计算当前状态下的“可用元操作 + 优先级”
            candidate_list = []  # [(priority, MetaOperation), ...]
            for mop in self.meta_operations:
                pr = mop.get_priority(self.state_manager)
                if pr is None:
                    continue  # 当前状态下禁用这个 meta
                candidate_list.append((pr, mop))

            # 没有任何候选元操作了，退出
            if not candidate_list:
                break

            # 按优先级从大到小排序
            candidate_list.sort(key=lambda x: x[0], reverse=True)

            executed = False
            for _, mop in candidate_list:
                if mop.can_execute(self.timer, self.state_manager):
                    mop.execute(self.timer, self.state_manager, record_list=rotation_log, character=self)
                    self._apply_time_regen()
                    steps += 1
                    executed = True
                    break

            if not executed:
                # 有候选，但没有任何一个能执行（资源不足等），退出
                break

        return rotation_log

    # ---------- 逻辑 2：基于单个 Operation 的贪心优先级 ----------
    def build_rotation_greedy_ops(self, max_steps=9999, op_priority=None):
        """
        逻辑2：
        对单个 Operation 做简单优先级排序，每次从优先级最高到最低，
        找到第一个 test() 为 True 的操作，立即执行并加入序列。
        如果一轮中没有任何操作可以执行，则终止。
        返回：记录列表。
        """
        rotation_log = []

        if op_priority is not None:
            # op_priority 可以是 Operation.id 的列表
            id_to_op = {op.id: op for op in self.operations}
            ordered_ops = [id_to_op[i] for i in op_priority if i in id_to_op]
        else:
            # 默认就按加入顺序
            ordered_ops = list(self.operations)

        for _ in range(max_steps):
            self.state_manager.update(self.timer)
            executed = False
            for op in ordered_ops:
                if op.test(state_manager=self.state_manager):
                    rec = op.operate(self.timer, self.state_manager)
                    rotation_log.append(rec)
                    self._after_operation_executed(op)
                    self._apply_time_regen()
                    executed = True
                    break
            if not executed:
                break

        return rotation_log

def make_operation_with_charges(
    character: "Character",
    op_id,
    time,
    resource_requirements,
    resource_outputs,
    resource_consumes,
    resource_produces,
    consume_upper_limit=None,
    consume_lower_limit=None,
    statesoutput=None,
    *,
    # === 充能相关 ===
    max_charges: int = 1,      # 最大充能层数，普通技能=1，特殊技能>1
    charge_cd: float | None = None,   # 单层充能CD（秒）。None 或 <=0 表示不随时间回复
    charge_res_id: str | None = None, # 充能资源在角色里的 id，不传则默认 "charge_<op_id>"
    # === 下面这些是你 Operation 的原始可选参数，照抄一遍，默认给 None ===
    resource_state_rules=None,
    state_requirements=None,
    state_forbids=None,
    resource_state_remove_rules=None,
    state_effects=None,
):
    """
    创建一个带“充能机制”的 Operation，并自动：
    - 为其配置充能 Resource（可复用已有的）
    - 为充能挂上 ResourceRegenRule（按 charge_cd 逐层回复）
    - 注册到 character.operations / character.resources / character.resource_regen_rules
    """

    # 防御式默认值处理
    statesoutput = list(statesoutput) if statesoutput else []
    resource_state_rules = list(resource_state_rules) if resource_state_rules else []
    state_requirements = list(state_requirements) if state_requirements else []
    state_forbids = list(state_forbids) if state_forbids else []
    resource_state_remove_rules = list(resource_state_remove_rules) if resource_state_remove_rules else []
    state_effects = list(state_effects) if state_effects else []

    # 1) 先按“没有充能”的方式创建 Operation
    op = Operation(
        id=op_id,
        time=time,
        resource_requirements=list(resource_requirements),
        resource_outputs=list(resource_outputs),
        resource_consumes=list(resource_consumes),
        resource_produces=list(resource_produces),
        consume_upper_limit=consume_upper_limit,
        consume_lower_limit=consume_lower_limit,
        statesoutput=statesoutput,
        resource_state_rules=resource_state_rules,
        state_requirements=state_requirements,
        state_forbids=state_forbids,
        resource_state_remove_rules=resource_state_remove_rules,
        state_effects=state_effects,
    )

    # 2) 准备“充能资源”
    if max_charges is None or max_charges <= 0:
        # 不需要充能机制，直接注册 op 返回
        character.add_operation(op)
        return op

    if charge_res_id is None:
        charge_res_id = f"charge_{op_id}"

    # 如果角色里已经有同名充能资源，就复用（方便多种形态共享充能池）
    if charge_res_id in character.resources:
        charge_res = character.resources[charge_res_id]
        # 确保上限至少是 max_charges
        charge_res.upper_limit = max(charge_res.upper_limit, max_charges)
        # 当前值不要超过上限
        if charge_res.current > charge_res.upper_limit:
            charge_res.current = charge_res.upper_limit
    else:
        # 否则新建一个充能资源，初始即满层
        charge_res = Resource(
            id=charge_res_id,
            upper_limit=max_charges,
            current=max_charges,
        )
        character.add_resource(charge_res)

    # 把一些充能信息挂在 op 身上（方便调试）
    op.max_charges = max_charges
    op.charge_cd = charge_cd
    op.charge_resource = charge_res

    # 3) 把充能当作“额外的资源需求”：每次操作消耗 1 层
    op.resource_requirements.append(charge_res)
    op.resource_consumes.append(1.0)

    # 4) 若设置了 charge_cd，则为充能挂一条时间回复规则
    if charge_cd is not None and charge_cd > 0:
        rate = 1.0 / charge_cd  # 每秒回复 1 / cd 层
        regen_rule = ResourceRegenRule(
            resource=charge_res,
            rate_per_sec=rate,
        )
        character.add_regen_rule(regen_rule)

    # 5) 最后把这个技能注册到角色
    character.add_operation(op)

    return op