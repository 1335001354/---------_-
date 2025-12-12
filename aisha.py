import math

class Aisha:
    """
    艾莎的攻击循环中，大招不能作为输出的终点，因为大招不会重置所有资源
    因此艾莎的攻击循环需要设置循环长度，在固定循环长度下，计算输出信息
    """
    def __init__(self, energy_total, requirements, attack_infos):
        self.heavy_activate_blade_threshold = requirements[0] # 重攻击解锁的飞刃数量阈值
        self.yy_blade_num = requirements[1] # 幽萤飞刃数量
        self.yy_ds_num = requirements[2] # 幽萤动势获取数量
        self.na_blade_num = requirements[3] # 普通攻击获得的飞刃数量
        self.xz_yy_num = requirements[4] # 旋斩获得的幽萤飞刃数量
        self.blade_upper_limit = requirements[5] # 飞刃获取上限
        self.ds_upper_limit = requirements[6] # 动势获取上限
        self.yy_upper_limit = requirements[7] # 幽萤飞刃获取上限
        self.tl_upper_limit = requirements[8] # 屠戮层数上限
        self.xz_yy_time = requirements[9] # 获得1幽萤需要的旋斩数量
        self.ds_yy_num = requirements[10] # 消耗动势获得的幽萤数量
        self.fa_blade_num = requirements[11] # 最后一击获得的飞刃数量
        self.blade_yy_threshold = requirements[12] # 重击飞刃消耗生成幽萤的数量阈值
        self.heavy_attack_damage_increase = requirements[13] # 重击伤害提升比例
        self.heavy_attack_blade_ds_threshold = requirements[14] # 重击获得动势的飞刃消耗阈值
        self.heavy_attack_blade_upper_limit = requirements[15] # 重击飞刃施法数量上限
        self.heavy_attack_damage_attach = requirements[16] # 重击伤害附加
        self.blade_damage_ratio = requirements[17] # 飞刃伤害倍率
        self.skill_ds_num = requirements[18] # 大招动势回复数量
        self.skill_yy_num = requirements[19] # 大招幽萤回复数量
        self.skill_blade_num = requirements[20] # 大招飞刃回复数量
        self.skill_damage_attach = requirements[21] # 大招伤害附加
        self.normal_attack_length = requirements[22] # 普通攻击长度
        self.heavy_attack_end_blade_threshold = requirements[23] # 重击结束的飞刃数量阈值
        self.skill_yy_num_start = requirements[24] # 大招开始时额外幽萤生成数量
        self.fy_blade_consume_threshold = requirements[25] # 漫天飞羽触发的飞刃阈值
        self.energy_total = requirements[26] # 能量上限
        self.fy_blade_num = requirements[27] # 漫天飞羽的发射数量
        self.fy_targeted_ratio = requirements[28] # 漫天飞羽的命中比例
        self.heavy_attack_blade_yy_ratio = requirements[29] # 重击飞刃生成幽萤的比例
        self.fa_yy_num = requirements[30] # 普攻最后一击生成幽萤的数量

        self.attack_infos = attack_infos

        self.current_blade = 0
        self.current_roughness = 0
        self.current_yy = 0
        self.current_ds = 0
        self.current_tl = 0
        self.current_energy = 0
        self.current_xz_count = 0 # 当前旋斩的释放次数
        self.current_yy_count = 0 # 当前幽萤的拾取次数
        self.current_heavy_attack_count = 0 # 当前重击的释放次数
        self.current_blade_consume_count = 0 # 当前飞刃的消耗次数
        self.current_normal_attack_count = 0
        self.current_heavy_attack_blade_count = 0 # 当前重击所释放的飞刃数量

        self.blade_consume_counter = 0
        self.yy_ground = 0
        self.yy_collect_speed_normal = 0.5
        self.yy_collect_speed_skill = 0.3 # 均为时间间隔
        self.ds_state_tag = False
        self.normal_attack_tag = True
        self.heavy_attack_tag = False
        self.skill_tag = False # 大招施法标志
        self.normal_attack_ids = [1,2,3,4]
        self.final_attack_num = 0
        self.timer = 0
        self.yy_upper_limit = 5
        self.real_attack_loop = []
        self.max_loop_length = 100
        self.tags =[self.skill_tag, self.heavy_attack_tag, self.normal_attack_tag]
    
    def check_tags(self):
        for tagi in range(len(self.tags)):
            if self.tags[tagi]:
                return tagi
        return -1
    
    def tags_define(self):
        self.skill_tag_define()
        self.heavy_attack_tag_define()
        self.normal_attack_define()

    def skill_tag_define(self):
        # 大招施法条件：能量大于等于能量上限，且进入幽萤拾取阶段
        if self.current_energy >= self.energy_total and self.current_yy >= 0.6 * self.yy_upper_limit:
            self.skill_tag = True
        else:
            self.skill_tag = False

    def skill_tag(self):
        if self.current_energy >= self.energy_total and self.current_yy >= 0.6 * self.yy_upper_limit:
            return True
        else:
            return False
    
    def skill_operation(self):
        """
        大招期间操作描述：
        1. 能量置为0
        2. 飞刃数量增加
        3. 幽萤数量降低
        4. 动势层数累计
        """
        self.current_energy = 0
        # 大招释放时幽萤的获取数量
        self.current_yy += self.skill_yy_num_start
        # 飞刃补充为飞刃数量上限
        intern = self.blade_upper_limit - self.current_blade - self.skill_blade_num
        yy_to_blade = math.ceil(intern / self.yy_blade_num)
        # 最终幽萤拾取数量取决于屠戮和飞刃的长板
        final_yy_consume = max(yy_to_blade, self.tl_upper_limit)
        self.current_yy -= final_yy_consume
        self.current_tl = min(final_yy_consume, self.tl_upper_limit)
        self.current_blade = self.current_blade + self.yy_blade_num * final_yy_consume
        print("大招拾取部分")
        print(self.current_blade)
        print(self.current_yy)
        self.current_ds += self.yy_ds_num * final_yy_consume
        # 技能结束后的资源添加
        self.current_blade = min(self.current_blade + self.skill_blade_num, self.blade_upper_limit)
        print("大招补充部分")
        print(self.current_blade)
        print(self.current_yy)
        self.current_ds = min(self.current_ds + self.skill_ds_num, self.ds_upper_limit)
        self.current_yy += self.skill_yy_num
        # 大招期间拾取幽萤的速度为0.35s/个
        self.timer += 0.35 * final_yy_consume
        # 技能结束后飞刃一定会达到上限值，屠戮一定会叠满，做合法性检查
        if self.current_blade != self.blade_upper_limit or self.current_tl != self.tl_upper_limit:
            raise ValueError("技能结束后飞刃未达到上限值或屠戮未叠满")
        damage_attach = 0
        self.real_attack_loop.append([8, self.current_blade_consume_count, self.timer, self.current_blade, self.current_yy, self.current_ds, self.current_tl, self.current_energy, damage_attach])
        self.tags_define()
    
    def heavy_attack_tag_define(self):
        if self.current_blade >= self.heavy_activate_blade_threshold or self.current_yy >= self.yy_upper_limit * 0.8:
            self.heavy_attack_tag = True
        else:
            self.heavy_attack_tag = False
    
    # 每一次重攻击前，都要检测当前的当前的飞刃数量是否大于等于重击的释放阈值
    def heavy_attack(self):
        # 重击所释放的每一把飞刃都有某概率生成幽萤
        blade_consume = min(self.current_blade, self.heavy_attack_blade_upper_limit)
        damage_attach = 0
        self.current_blade -= blade_consume
        self.current_heavy_attack_blade_count += blade_consume
        self.timer += self.attack_infos[5][1]
        self.current_roughness += blade_consume * self.attack_infos[5][4]
        self.current_energy += blade_consume * self.attack_infos[5][5]
        self.current_yy += blade_consume * self.heavy_attack_blade_yy_ratio
        self.real_attack_loop.append([6, self.current_blade_consume_count, self.timer, self.current_blade, self.current_yy, self.current_ds, self.current_tl, self.current_energy, damage_attach])
        self.current_blade_consume_count += blade_consume
        if self.current_blade_consume_count >= self.fy_blade_consume_threshold:
            self.fy()
            self.current_blade_consume_count = 0

    def fy(self):
        # 回能, 28为命中率
        self.current_energy += self.fy_blade_num * self.attack_infos[5][5] * self.fy_targeted_ratio
        # 削韧
        self.current_roughness += self.fy_blade_num * self.attack_infos[5][4] * self.fy_targeted_ratio
        # 计时
        self.timer += 0
        # 纳入攻击循环
        self.real_attack_loop.append([13, self.current_blade_consume_count, self.timer, self.current_blade, self.current_yy, self.current_ds, self.current_tl, self.current_energy, 0])

        
    def heavy_attack_operation(self):
        """
        1. 当大招能量>80%时，打出当前所有的飞刃
        2. 常规状态下，若场上幽萤数量大于等于幽萤的拾取阈值，则进入重击循环
        3. 重击循环中，操作逻辑为0.3s的位移，检测飞刃数量，若飞刃数量大次循环后，检于等于重击的释放阈值，则释放重击，否则检测动势层数，
           若动势层数已满，则进入动势状态并打完所有的旋斩，若未满，则进入普攻循环，每测飞刃数量
           若飞刃数量大于重击的释放阈值，则释放重击，循环结束。
        4. 当场上的的幽萤数量达到上限时，打空所有飞刃,并拾起3个幽萤
        """
        print("重击循环开始")
        while not self.skill_tag and self.heavy_attack_tag:
            # 当大招能量>80%时，打出当前所有的飞刃
            # print(self.current_energy, self.current_blade, self.current_yy, self.yy_upper_limit)
            if self.current_energy >= self.energy_total * 0.8:
                while self.current_blade > self.heavy_activate_blade_threshold and not self.skill_tag:
                    self.heavy_attack()
                    print("大招前的重击循环")
                print("大招前的飞刃已打空")
            if self.current_yy >= self.yy_upper_limit * 0.8:
                while self.current_blade > self.heavy_activate_blade_threshold and not self.skill_tag:
                    self.heavy_attack()
                    print("幽萤达到上限时的重击循环")
                self.current_yy -= 3
                self.timer += 0.3 * 3
                self.current_blade = min(self.current_blade + self.yy_blade_num * 3, self.blade_upper_limit)
                self.current_ds = min(self.current_ds + self.yy_ds_num * 3, self.ds_upper_limit)
                print("幽萤达到上限时，打空所有飞刃")
            # 场上有幽萤的情况下
            elif self.current_yy >= 1:
                while not self.skill_tag and self.current_energy < self.energy_total and self.current_yy < self.yy_upper_limit:
                    self.timer += 0.3
                    self.current_blade += self.yy_blade_num
                    self.current_ds += self.yy_ds_num
                    # 进入动势状态，打完所有的旋斩
                    if self.current_ds == self.ds_upper_limit:
                        self.ds_state_operation()
                        print("旋斩已经打完")
                    # 可以发动重攻击时，进入重击循环，同时检测能量是否到达了上限,同时将上述判断条件重新检测
                    if self.current_blade >= self.heavy_activate_blade_threshold:
                        self.heavy_attack()
                        print("重击循环")
                print("完成普通的重击循环")
            else:
                if self.current_blade >= self.heavy_activate_blade_threshold:
                    self.heavy_attack()  
                else:
                    self.heavy_attack_tag = False
                    print("重击循环结束")
            self.tags_define()

                            
    def ds_state_operation(self):
        # 旋斩
        for i in range(int(self.ds_upper_limit)):
            self.timer += self.attack_infos[4][1]
            self.current_blade_consume_count += self.fa_blade_num
            # 普攻最后一击的伤害附加
            self.current_roughness += self.attack_infos[4][4] + self.attack_infos[5][4] * self.fa_blade_num
            self.current_energy += self.attack_infos[4][5] * self.fa_blade_num
            if self.current_blade_consume_count >= self.fy_blade_consume_threshold:
                # 漫天飞羽
                self.fy()
                self.current_blade_consume_count = 0
            damage_attach = 0
            self.current_xz_count += 1
            if self.current_xz_count % self.xz_yy_time == 0:
                self.current_yy += 2 * self.xz_yy_num
            self.real_attack_loop.append([5, self.current_blade_consume_count, self.timer, self.current_blade, self.current_yy, self.current_ds, self.current_tl, self.current_energy, damage_attach])
        self.current_ds = 0


    def normal_attack_define(self):
        # 若当前大招tag未激活，重攻tag未激活，则激活普通攻击tag
        if not self.skill_tag and not self.heavy_attack_tag:
            self.normal_attack_tag = True
        else:
            self.normal_attack_tag = False

    def normal_attack_operation(self):
        while self.normal_attack_tag:
            self.normal_attack()
            self.tags_define()
    
    def normal_attack(self): # times为攻击次数
        self.current_blade += self.na_blade_num
        self.timer += self.attack_infos[int(self.current_normal_attack_count % self.normal_attack_length)][1]
        self.current_roughness += self.attack_infos[int(self.current_normal_attack_count % self.normal_attack_length)][4]
        self.current_energy += self.attack_infos[int(self.current_normal_attack_count % self.normal_attack_length)][5]
        if self.current_blade >= self.heavy_activate_blade_threshold:
            self.heavy_attack_tag = True
        self.real_attack_loop.append([self.normal_attack_ids[int(self.current_normal_attack_count % self.normal_attack_length)], self.current_blade_consume_count, self.timer, self.current_blade, self.current_yy, self.current_ds, self.current_tl, self.current_energy, self.current_roughness])
        # 最后一击
        if self.current_normal_attack_count % self.normal_attack_length == self.normal_attack_length - 1:
            # 最后一击会发射飞刃
            self.current_blade_consume_count += self.fa_blade_num
            if self.current_blade_consume_count >= self.fy_blade_consume_threshold:
                self.fy()
                self.current_blade_consume_count = 0
            self.current_yy = min(self.current_yy + self.fa_yy_num, self.yy_upper_limit)
        self.current_normal_attack_count += 1

    def final_attackloop_define(self):
        while len(self.real_attack_loop) < self.max_loop_length:
            # 0为大招启动，1为重攻击状态，2为普通攻击状态
            # print(self.normal_attack_tag, self.heavy_attack_tag, self.skill_tag)
            if self.skill_tag == True:
                self.skill_operation()
            elif self.heavy_attack_tag == True:
                self.heavy_attack_operation()
            elif self.normal_attack_tag == True:
                self.normal_attack_operation()
            print(self.real_attack_loop)
        return [i for i in self.real_attack_loop]
        



