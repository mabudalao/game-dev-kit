# -*- coding: utf-8 -*-
"""游戏状态机（State Machine）。

用途：管理场景/角色状态，避免满屏 if state == ... 的写法。
每个状态处理自己的输入、更新和切换逻辑。

运行：python state_machine.py（纯标准库）
"""
from abc import ABC, abstractmethod


class State(ABC):
    @abstractmethod
    def enter(self, ctx):
        """进入状态时执行一次"""

    @abstractmethod
    def update(self, ctx, dt):
        """每帧更新，返回要切换到的新状态（或 None 保持）。"""

    def exit(self, ctx):
        """离开状态时执行一次"""


# ---- 具体状态 ----
class MenuState(State):
    def enter(self, ctx):
        print("[菜单] 显示开始界面")

    def update(self, ctx, dt):
        if ctx.input == "start":
            return PlayingState()
        return None


class PlayingState(State):
    def enter(self, ctx):
        print("[游戏] 进入关卡")

    def update(self, ctx, dt):
        if ctx.input == "pause":
            return PausedState()
        if ctx.input == "die":
            return GameOverState()
        ctx.score += int(10 * dt)
        return None


class PausedState(State):
    def enter(self, ctx):
        print("[暂停] 游戏已暂停")

    def update(self, ctx, dt):
        if ctx.input == "resume":
            return PlayingState()
        return None


class GameOverState(State):
    def enter(self, ctx):
        print("[结束] 最终得分: %d" % ctx.score)

    def update(self, ctx, dt):
        return None


class Context:
    """共享数据：所有状态都能读写的上下文。"""
    def __init__(self):
        self.score = 0
        self.input = None


class StateMachine:
    def __init__(self, ctx, initial: State):
        self.ctx = ctx
        self.state = None
        self.transition_to(initial)

    def transition_to(self, new_state: State):
        if self.state:
            self.state.exit(self.ctx)
        self.state = new_state
        self.state.enter(self.ctx)

    def handle(self, input_name, dt=1.0):
        self.ctx.input = input_name
        nxt = self.state.update(self.ctx, dt)
        if nxt:
            self.transition_to(nxt)


if __name__ == "__main__":
    fsm = StateMachine(Context(), MenuState())
    for action in ["start", "idle", "idle", "pause", "resume", "die"]:
        print("输入: %s" % action)
        fsm.handle(action)
    print("最终状态: %s" % type(fsm.state).__name__)
