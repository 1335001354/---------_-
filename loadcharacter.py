import xlwings as xw
import json
from character import (
    Timer,
    Character,
    Resource,
    State,
    StateResourceEffect,
    OperationAccelerate,
    OperationResourceEfficiency,
    Operation,
    StateEffect,
    ResourceStateRule,
    ResourceStateRemoveRule,
    ResourceRegenRule,
    ResourceThreshold,
    MetaOperation,
    OperationTriggeredStateRule,
)

def _read_table(sheet):
    vals = sheet.used_range.value
    header, rows = vals[0], vals[1:]
    return [dict(zip(header, r)) for r in rows if any(r)]

def _as_bool(v):
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "t"):
        return True
    if s in ("0", "false", "no", "n", "f", ""):
        return False
    # 兜底：能转数字就按非0
    try:
        return bool(int(float(s)))
    except Exception:
        return False



def _as_list(s):
    if s is None or s == "":
        return []
    return [x.strip() for x in str(s).split(",") if x.strip()]

def _parse_list(v):
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if s.startswith("["):
        try:
            return json.loads(s)
        except Exception:
            pass
    return [x for x in s.split(";") if x]

def _parse_required_states(val, state_map):
    res = []
    for item in _parse_list(val):
        parts = str(item).split(":")
        sid = parts[0]
        min_stack = int(parts[1]) if len(parts) > 1 else 1
        if sid in state_map:
            res.append((state_map[sid], min_stack))
    return res

def _parse_forbidden_states(val, state_map):
    res = []
    for item in _parse_list(val):
        sid = str(item).split(":")[0]
        if sid in state_map:
            res.append(state_map[sid])
    return res

def _parse_resource_thresholds(val, res_map):
    res = []
    for item in _parse_list(val):
        parts = str(item).split(":")
        if len(parts) >= 2:
            rid = parts[0]
            thr = float(parts[1])
            mode = parts[2] if len(parts) >= 3 else ">="
            if rid in res_map:
                res.append(ResourceThreshold(res_map[rid], thr, mode))
    return res

@xw.func
def build_character_from_excel(path: str, sheet_prefix: str = ""):
    wb = xw.Book(path)
    sh = lambda name: wb.sheets[f"{sheet_prefix}{name}"]

    # 资源
    res_map = {}
    for r in _read_table(sh("Resources")):
        res_map[r["id"]] = Resource(r["id"], float(r["upper_limit"]), float(r["current"]))

    # 状态
    state_map = {}
    for r in _read_table(sh("States")):
        st = State(
            id=r["id"],
            current=float(r["current"]),
            upper_limit=float(r["upper_limit"]),
            time=float(r["time"]),
            type=int(r["type"]),
            length=int(r["length"]),
            expire_mode=r.get("expire_mode", "time") or "time",
        )
        state_map[st.id] = st

    # 状态↔资源
    for r in _read_table(sh("StateResourceEffects")):
        st = state_map[r["state_id"]]
        res = res_map[r["resource_id"]]
        st.resource_effects.append(
            StateResourceEffect(
                resource=res,
                on_add=float(r.get("on_add", 0) or 0),
                on_remove=float(r.get("on_remove", 0) or 0),
                per_stack=_as_bool(r.get("per_stack", 0)),
                ratio_on_add=None if r.get("ratio_on_add") in (None, "") else float(r["ratio_on_add"]),
                ratio_on_remove=None if r.get("ratio_on_remove") in (None, "") else float(r["ratio_on_remove"]),
            )
        )

    # 状态→元操作优先级
    for r in _read_table(sh("StateMetaPriorityRules")):
        st = state_map[r["state_id"]]
        st.meta_priority_rules.append((r["meta_id"], float(r["delta"]), int(r.get("min_stack", 1) or 1)))

    # 状态→操作加速
    for r in _read_table(sh("StateOpAccelerateRules")):
        st = state_map[r["state_id"]]
        st.op_accelerate_rules.append(
            OperationAccelerate(
                operation=r["op_id"],  # 先放 id，占位，稍后替换成对象
                ratio=float(r.get("ratio", 0) or 0),
                ratio_per_stack=float(r.get("ratio_per_stack", 0) or 0),
                by_current_stack=_as_bool(r.get("by_current_stack", 1)),
                min_ratio=float(r.get("min_ratio", 0) or 0),
                max_ratio=float(r.get("max_ratio", 0.95) or 0.95),
            )
        )

    # 状态→操作效率
    for r in _read_table(sh("StateOpEfficiencyRules")):
        st = state_map[r["state_id"]]
        st.op_efficiency_rules.append(
            OperationResourceEfficiency(
                operation=r["op_id"],  # 先放 id，占位，稍后替换成对象
                target=r.get("target", "both"),
                resource=None if r.get("resource_id") in (None, "") else res_map[r["resource_id"]],
                mul=float(r.get("mul", 1) or 1),
                mul_per_stack=float(r.get("mul_per_stack", 0) or 0),
                by_current_stack=_as_bool(r.get("by_current_stack", 1)),
                min_mul=float(r.get("min_mul", 0) or 0),
                max_mul=float(r.get("max_mul", 10) or 10),
            )
        )

    # 操作
    op_map = {}
    for r in _read_table(sh("Operations（基础）")):  # 列: op_id, base_time
        op_map[r["op_id"]] = Operation(
            id=r["op_id"],
            time=float(r["base_time"]),
            resource_requirements=[],
            resource_outputs=[],
            resource_consumes=[],
            resource_produces=[],
            statesoutput=[],
            consume_upper_limits=[],
            consume_lower_limits=[],
            max_charges=float(r["max_charges"]) if r.get("max_charges") not in (None, "") else None,
            charge_cd=float(r["charge_cd"]) if r.get("charge_cd") not in (None, "") else None,
        )

    # 操作消耗
    for r in _read_table(sh("OperationConsumes")):  # op_id, resource_id, consume, consume_upper?
        op = op_map[r["op_id"]]
        res = res_map[r["resource_id"]]
        op.resource_requirements.append(res)
        op.resource_consumes.append(float(r["consume"]))
        op.consume_upper_limits.append(None if r.get("consume_upper") in ("", None) else float(r["consume_upper"]))
        op.consume_lower_limits.append(None if r.get("consume_lower") in ("", None) else float(r["consume_lower"]))

    # 操作产出
    for r in _read_table(sh("OperationProduces")):  # op_id, resource_id, produce
        op = op_map[r["op_id"]]
        op.resource_outputs.append(res_map[r["resource_id"]])
        op.resource_produces.append(float(r["produce"]))

    # 操作施加状态
    for r in _read_table(sh("OperationStatesOutput")):
        op_map[r["op_id"]].statesoutput.append(state_map[r["state_id"]])

    # 操作状态需求/禁止
    for r in _read_table(sh("OperationStateRequirements")):
        op_map[r["op_id"]].state_requirements.append((state_map[r["state_id"]], int(r.get("min_stack", 1) or 1)))
    for r in _read_table(sh("OperationStateForbids")):
        op_map[r["op_id"]].state_forbids.append(state_map[r["state_id"]])

    # 操作状态修正
    for r in _read_table(sh("OperationStateEffects")):
        op_map[r["op_id"]].state_effects.append(
            StateEffect(
                state=state_map[r["state_id"]],
                target=r.get("target", "both"),
                resource=None if r.get("resource_id") in (None, "") else res_map[r["resource_id"]],
                op=r.get("op", "mul"),
                value=float(r.get("value", 1) or 1),
                min_stack=int(r.get("min_stack", 1) or 1),
                max_stack=None if r.get("max_stack") in (None, "") else int(r["max_stack"]),
            )
        )

    # 资源→状态规则
    for r in _read_table(sh("ResourceStateRules")):
        op = op_map[r["op_id"]]
        op.resource_state_rules.append(
            ResourceStateRule(
                resource=res_map[r["resource_id"]],
                threshold=float(r["threshold"]),
                state=state_map[r["state_id"]],
                mode=r.get("mode", ">="),
                once=_as_bool(r.get("once", 1)),
            )
        )

    # 资源→移除状态规则
    for r in _read_table(sh("ResourceStateRemoveRules")):
        op = op_map[r["op_id"]]
        op.resource_state_remove_rules.append(
            ResourceStateRemoveRule(
                resource=res_map[r["resource_id"]],
                state=state_map[r["state_id"]],
                threshold=float(r["threshold"]),
                mode=r.get("mode", "<="),
                require_active=_as_bool(r.get("require_active", 1)),
            )
        )

    # 时间回复规则
    regen_rules = []
    rr_rows = _read_table(sh("RegenRules"))  # rule_id, resource_id, rate_per_sec
    req_rows = _read_table(sh("RegenRuleStateRequirements"))
    forb_rows = _read_table(sh("RegenRuleStateForbids"))
    for r in rr_rows:
        reqs = [(state_map[x["state_id"]], int(x.get("min_stack", 1) or 1)) for x in req_rows if x["rule_id"] == r["rule_id"]]
        forbs = [state_map[x["state_id"]] for x in forb_rows if x["rule_id"] == r["rule_id"]]
        regen_rules.append(
            ResourceRegenRule(
                resource=res_map[r["resource_id"]],
                rate_per_sec=float(r["rate_per_sec"]),
                state_requirements=reqs,
                state_forbids=forbs,
            )
        )

    # 元操作
    meta_map = {}
    for r in _read_table(sh("MetaOperations")):  # meta_id, type, base_priority, n
        meta_map[r["meta_id"]] = MetaOperation(
            id=r["meta_id"],
            operations=[],
            type=int(r.get("type", 1) or 1),
            base_priority=int(r.get("base_priority", 0) or 0),
            on_success_states=[],
            n=None if r.get("n") in ("", None) else int(r["n"]),
        )

    # 元操作序列
    rows = _read_table(sh("MetaOpOperations"))
    rows.sort(key=lambda x: (x["meta_id"], int(x.get("order", 0) or 0)))
    for r in rows:  # meta_id, order, op_id
        meta_map[r["meta_id"]].operations.append(op_map[r["op_id"]])

    # 元操作成功施加状态
    for r in _read_table(sh("MetaOpOnSuccessStates")):
        meta_map[r["meta_id"]].on_success_states.append(state_map[r["state_id"]])

    # 元操作状态需求/禁止
    for r in _read_table(sh("MetaOpStateRequirements")):
        meta_map[r["meta_id"]].meta_state_requirements.append((state_map[r["state_id"]], int(r.get("min_stack", 1) or 1)))
    for r in _read_table(sh("MetaOpStateForbids")):
        meta_map[r["meta_id"]].meta_state_forbids.append(state_map[r["state_id"]])
    
    for st in state_map.values():
        fixed = []
        for rule in st.meta_priority_rules:
            meta_id, delta, min_stack = rule if len(rule) >= 3 else (rule[0], rule[1], 1)
            if isinstance(meta_id, str) and meta_id in meta_map:
                fixed.append((meta_map[meta_id], float(delta), int(min_stack)))
            else:
                fixed.append(rule)
        st.meta_priority_rules = fixed

    # 触发规则（单表，若有子表请自行拆分）
    trig_rules = []
    for r in _read_table(sh("OperationTriggeredStateRules")):  # trigger_op_id, target_state_id, add_stacks, once_per_operation_call, required_states?, forbidden_states?, resource_thresholds?
        trig_rules.append(
            OperationTriggeredStateRule(
                trigger_operation=op_map[r["trigger_op_id"]],
                target_state=state_map[r["target_state_id"]],
                required_states=_parse_required_states(r.get("required_states", ""), state_map),
                forbidden_states=_parse_forbidden_states(r.get("forbidden_states", ""), state_map),
                resource_thresholds=_parse_resource_thresholds(r.get("resource_thresholds", ""), res_map),
                add_stacks=int(r.get("add_stacks", 1) or 1),
                once_per_operation_call=_as_bool(r.get("once_per_operation_call", 1)),
            )
        )

    # 将占位的 op_id 字符串替换成真正的对象（加速/效率规则）
    for st in state_map.values():
        for acc in getattr(st, "op_accelerate_rules", []):
            if isinstance(acc.operation, str):
                acc.operation = op_map[acc.operation]
        for eff in getattr(st, "op_efficiency_rules", []):
            if isinstance(eff.operation, str):
                eff.operation = op_map[eff.operation]

    # 组装角色
    ch = Character("xl_factory", Timer(), resources=list(res_map.values()), states=list(state_map.values()))
    ch.resource_regen_rules = regen_rules
    for op in op_map.values():
        ch.add_operation(op)
    for m in meta_map.values():
        ch.add_meta_operation(m)
    for tr in trig_rules:
        ch.add_op_trigger_rule(tr)

    # 返回可序列化摘要
    return {
        "name": ch.name,
        "resources": {k: {"cur": v.current, "upper": v.upper_limit} for k, v in res_map.items()},
        "states": list(state_map.keys()),
        "operations": list(op_map.keys()),
        "meta_operations": {k: [op.id for op in m.operations] for k, m in meta_map.items()},
        "regen_rules": len(regen_rules),
        "trigger_rules": len(trig_rules),
    }
