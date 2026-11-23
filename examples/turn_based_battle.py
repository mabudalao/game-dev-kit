# -*- coding: utf-8 -*-
"""回合制战斗循环（Turn-Based Battle Loop）。

演示回合制游戏最核心的三件事：
  1. 行动队列：按速度排序，速度高的单位行动更频繁
  2. 统一调度：玩家回合和 AI 回合走同一套"执行行动"逻辑
  3. 行动状态机：每个回合 = 选指令 → 选目标 → 结算 → 判定胜负

运行：python turn_based_battle.py（纯标准库，无需安装依赖）
"""
import random

# ---------- 实体 ----------
class Unit:
    def __init__(self, name, hp, atk, speed, is_player=False):
        self.name = name
        self.max_hp = hp
        self.hp = hp
        self.atk = atk
        self.speed = speed
        self.is_player = is_player
        self.defending = False   # 本回合是否防御

    def alive(self):
        return self.hp > 0

    def take_damage(self, dmg):
        if self.defending:
            dmg = max(1, dmg // 2)   # 防御减伤一半
        self.hp = max(0, self.hp - dmg)
        return dmg

    def __repr__(self):
        return "%s(HP %d/%d)" % (self.name, self.hp, self.max_hp)


# ---------- 行动指令 ----------
def action_attack(actor, target):
    """普通攻击：伤害 = 攻击力 ± 20% 浮动。"""
    dmg = int(actor.atk * random.uniform(0.8, 1.2))
    real = target.take_damage(dmg)
    print("  %s 攻击 %s，造成 %d 点伤害" % (actor.name, target.name, real))
    return real


def action_skill(actor, target):
    """技能：1.5 倍伤害，消耗固定次数（示例里不设蓝条）。"""
    dmg = int(actor.atk * 1.5 * random.uniform(0.9, 1.1))
    real = target.take_damage(dmg)
    print("  %s 释放技能击中 %s，造成 %d 点伤害" % (actor.name, target.name, real))
    return real


def action_defend(actor):
    actor.defending = True
    print("  %s 进入防御姿态（本回合受伤减半）" % actor.name)


# ---------- 行动队列 ----------
class TurnQueue:
    """按速度排序的行动队列。每轮结束后把行动者按速度重新插入。"""
    def __init__(self, units):
        self.units = list(units)

    def next(self):
        """取当前行动者：速度越高越靠前；同速随机。"""
        candidates = [u for u in self.units if u.alive()]
        if not candidates:
            return None
        candidates.sort(key=lambda u: (-u.speed, random.random()))
        return candidates[0]

    def alive_teams(self):
        players = [u for u in self.units if u.is_player and u.alive()]
        enemies = [u for u in self.units if not u.is_player and u.alive()]
        return players, enemies


# ---------- 玩家决策（示例用自动策略，真实游戏这里等 UI 输入） ----------
def choose_player_action(actor, enemies):
    """示例策略：血量低于 30% 且随机触发时防御，否则普攻/技能交替。"""
    if actor.hp < actor.max_hp * 0.3 and random.random() < 0.4:
        return ("defend", None)
    if random.random() < 0.3:
        return ("skill", random.choice(enemies))
    return ("attack", random.choice(enemies))


def choose_ai_action(actor, players):
    """AI 决策：随机普攻，偶尔防御。"""
    if random.random() < 0.2:
        return ("defend", None)
    return ("attack", random.choice(players))


# ---------- 战斗主循环 ----------
def battle(players, enemies):
    queue = TurnQueue(players + enemies)
    turn = 0
    MAX_TURN = 60   # 防止死循环的保险

    print("=== 战斗开始 ===")
    print("我方:", players)
    print("敌方:", enemies)
    print()

    while turn < MAX_TURN:
        players_alive, enemies_alive = queue.alive_teams()

        # 胜负判定
        if not players_alive:
            print("=== 战斗失败 ==="); return "lose"
        if not enemies_alive:
            print("=== 战斗胜利 ==="); return "win"

        actor = queue.next()
        turn += 1
        actor.defending = False   # 每回合开始清除上回合防御状态
        print("[回合 %d] 轮到 %s" % (turn, actor.name))

        if actor.is_player:
            cmd, target = choose_player_action(actor, enemies_alive)
        else:
            cmd, target = choose_ai_action(actor, players_alive)

        # 统一执行行动
        if cmd == "attack":
            action_attack(actor, target)
        elif cmd == "skill":
            action_skill(actor, target)
        elif cmd == "defend":
            action_defend(actor)

        print("  状态:", queue.alive_teams()[0], "vs", queue.alive_teams()[1])
        print()

    print("=== 达到回合上限，战斗结束 ===")
    return "timeout"


if __name__ == "__main__":
    random.seed()
    hero = Unit("勇者", 120, 18, 12, is_player=True)
    mage = Unit("法师", 80, 22, 9, is_player=True)
    result = battle(
        players=[hero, mage],
        enemies=[Unit("哥布林", 60, 10, 8), Unit("兽人", 90, 14, 6)],
    )
    print("战斗结果:", result)
