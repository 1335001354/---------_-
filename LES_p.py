import xlwings as xw
import numpy as np
from aisha import Aisha

@xw.func
def sumup(attack_loop, data_fetch, data_return):
    result = 0
    for i in attack_loop:
        for j in data_fetch:
            if int(i) == int(j):
                result += data_return[int(j)]
    return result

@xw.func
def customize_interpolate_se(start, end_value, steps, order):
    """
    生成长度 steps+1 的序列：
    y[i] = start + (end_value - start) * (i/steps)^order,  i=0..steps
    使 y[0]=start, y[steps]=end_value
    """
    try:
        n = int(steps)
    except Exception:
        return "steps must be integer-like"

    if n < 0:
        return "steps must be >= 0"

    # n == 0 时只返回终点（也可返回 start，看你的需求）
    if n == 0:
        return [[end_value]]

    # 计算序列
    denom = (n ** order) if order != 0 else 1  # 防止除以 0
    seq = [start + (end_value - start) * ((i ** order) / denom) for i in range(n + 1)]

    # 返回列向量给 Excel
    return [[v] for v in seq]

@xw.func
def tj_attackloop(energy_total, yj_total, bd_total, attack_1_yj_add, attack_2_yj_add, heavy_attack_yj_cost, attack_1_energy_add, attack_2_energy_add, heavy_attack_energy_add, yj_revert_threshold, normal_attack_time, normal_attack_loop_bd_time, bd_add_time, three_heavy_bd_revert, bd_consume_ratio=1, original_normal_attack_length=5):
    """
    0表示重击，1表示拔刀斩, 2表示普通攻击
    优先级：重击>拔刀斩>普通攻击
    """
    current_yj_consume = 0
    current_yj = yj_total
    current_bd = bd_total
    skill_tag = True
    real_attack_loop = []
    current_energy = 0
    normal_attack_loop_time_count = 0
    revert_time = 0
    final_attack_time = 0
    heavy_attack_time = 0
    bd_time = 0
    heavy_attack_ids = [0,1,2]
    normal_attack_ids = [4,5,6,7,8]
    operation_change_time = 0
    while skill_tag:
        heavy_attack_id = 0
        while current_yj >= heavy_attack_yj_cost:
            real_attack_loop.append([heavy_attack_ids[heavy_attack_id], current_yj, current_bd, current_energy, revert_time, final_attack_time, heavy_attack_time, bd_time, operation_change_time]) # 0 表示重击
            heavy_attack_id += 1
            if heavy_attack_id == len(heavy_attack_ids):
                heavy_attack_id = 0
                current_bd = min(current_bd + three_heavy_bd_revert, bd_total)
            current_yj -= heavy_attack_yj_cost
            print(current_yj)
            current_yj_consume += heavy_attack_yj_cost
            current_energy += heavy_attack_energy_add
            heavy_attack_time += 1
            if current_yj_consume >= yj_revert_threshold:
                current_yj = yj_total
                current_yj_consume = 0
                revert_time += 1
            if current_energy >= energy_total:
                operation_change_time += 1
                real_attack_loop.append([9, current_yj, current_bd, current_energy, revert_time, final_attack_time, heavy_attack_time, bd_time, operation_change_time]) # 3 表示大招
                skill_tag = False
                break

        operation_change_time += 1

        normal_attack_time_count = 0
        while current_yj < yj_total and skill_tag:
            if current_bd >= 1:
                real_attack_loop.append([3, current_yj, current_bd, current_energy, revert_time, final_attack_time, heavy_attack_time, bd_time, operation_change_time]) # 1 表示拔刀斩
                print("拔刀斩")
                current_bd -= bd_consume_ratio
                current_yj = min(current_yj + attack_1_yj_add, yj_total)
                current_energy += attack_1_energy_add
                bd_time += 1
                normal_attack_loop_time_count += 1
                if normal_attack_loop_time_count == normal_attack_loop_bd_time:
                    current_bd = min(current_bd + bd_add_time, bd_total) # bd_add_time 表示每n次最后一击的拔刀斩次数回复数量
                    normal_attack_loop_time_count = 0
                if current_energy >= energy_total:
                    real_attack_loop.append([9, current_yj, current_bd, current_energy, revert_time, final_attack_time, heavy_attack_time, bd_time, operation_change_time]) # 3 表示大招
                    skill_tag = False
                    break
            else:
                real_attack_loop.append([normal_attack_ids[int(original_normal_attack_length - normal_attack_time + normal_attack_time_count)], current_yj, current_bd, current_energy, revert_time, final_attack_time, heavy_attack_time, bd_time, operation_change_time]) # 2 表示普通攻击
                print("普通攻击")
                current_yj = min(current_yj + attack_2_yj_add, yj_total)
                current_energy += attack_2_energy_add
                normal_attack_time_count += 1
                if int(original_normal_attack_length - normal_attack_time + normal_attack_time_count) == len(normal_attack_ids):
                    normal_attack_loop_time_count += 1
                    normal_attack_time_count = 0
                    if normal_attack_loop_time_count == normal_attack_loop_bd_time:
                        current_bd = min(current_bd + bd_add_time, bd_total)
                        normal_attack_loop_time_count = 0
                        final_attack_time += 1
                if current_energy >= energy_total:
                    real_attack_loop.append([9, current_yj, current_bd, current_energy, revert_time, final_attack_time, heavy_attack_time, bd_time, operation_change_time]) # 3 表示大招
                    skill_tag = False
                    break
        operation_change_time += 1
                
    return real_attack_loop


@xw.func
def as_attackloop(energy_total, requirements, attack_infos):
    aisha = Aisha(energy_total, requirements, attack_infos)
    result = aisha.final_attackloop_define()
    for i in result:
        print(len(i))
    return result

if __name__ == "__main__":
    xw.serve()