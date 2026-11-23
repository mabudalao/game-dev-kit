# -*- coding: utf-8 -*-
"""固定时间步的游戏主循环（Fixed Timestep Game Loop）。

为什么需要：不同电脑帧率不同，若逻辑跟着帧率走，高帧率机器游戏就"快"。
固定步长让逻辑以恒定速率更新，渲染用插值平滑，保证所有机器体验一致。

运行：python game_loop.py  （纯标准库，无需安装依赖）
"""
import time

class GameLoop:
    def __init__(self, update_rate=60):
        self.dt = 1.0 / update_rate          # 逻辑步长（秒）
        self.max_frame = 0.25                # 防止卡顿后"死亡螺旋"
        self.accumulator = 0.0
        self.running = False

    def update(self, dt):
        """游戏逻辑更新：移动、碰撞、AI 都放这里。dt 恒等于 self.dt。"""
        pass

    def render(self, alpha):
        """渲染。alpha 是当前帧在两次逻辑更新间的插值比例(0~1)。"""
        pass

    def run(self):
        self.running = True
        last = time.perf_counter()
        frame_count = 0
        while self.running:
            now = time.perf_counter()
            elapsed = min(now - last, self.max_frame)  # 限制单帧最大时长
            last = now
            self.accumulator += elapsed

            # 攒够一个步长就更新一次，可能一帧更新多次或零次
            while self.accumulator >= self.dt:
                self.update(self.dt)
                self.accumulator -= self.dt

            alpha = self.accumulator / self.dt          # 插值比例
            self.render(alpha)

            frame_count += 1
            if frame_count >= 600:                      # 演示：跑 600 帧自动停
                self.running = False


class Demo(GameLoop):
    """演示：一个小球的 x 坐标随时间匀速移动。"""
    def __init__(self):
        super().__init__(update_rate=60)
        self.x = 0.0
        self.speed = 5.0  # 每秒 5 单位——无论帧率多少，速度都一样

    def update(self, dt):
        self.x += self.speed * dt

    def render(self, alpha):
        # 用插值算出平滑显示位置（真实项目里这里画到屏幕）
        shown_x = self.x + self.speed * self.dt * alpha
        if int(shown_x * 10) % 50 == 0:
            print("球位置: %.1f" % shown_x)


if __name__ == "__main__":
    print("固定时间步主循环演示（运行 600 帧）...")
    demo = Demo()
    t0 = time.perf_counter()
    demo.run()
    print("结束：模拟 %.2f 秒游戏时间，真实耗时 %.2f 秒，最终 x=%.1f" % (
        demo.x / demo.speed, time.perf_counter() - t0, demo.x))
