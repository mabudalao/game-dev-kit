# -*- coding: utf-8 -*-
"""2D 碰撞检测：AABB 与圆形。

游戏里最基础的碰撞判断。AABB 用于矩形（角色、地面），圆形用于子弹、爆炸范围。
还演示了空间网格划分——对象多时避免 O(n²) 两两检测。

运行：python collision.py（纯标准库）
"""
import math


class AABB:
    """轴对齐矩形：用左上角 + 宽高表示。"""
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def left(self): return self.x
    @property
    def right(self): return self.x + self.w
    @property
    def top(self): return self.y
    @property
    def bottom(self): return self.y + self.h

    def overlaps(self, other: "AABB") -> bool:
        """两个矩形是否相交。"""
        return (self.left < other.right and self.right > other.left and
                self.top < other.bottom and self.bottom > other.top)


class Circle:
    def __init__(self, cx, cy, r):
        self.cx, self.cy, self.r = cx, cy, r

    def overlaps(self, other: "Circle") -> bool:
        dx, dy = self.cx - other.cx, self.cy - other.cy
        return dx * dx + dy * dy <= (self.r + other.r) ** 2

    def overlaps_aabb(self, box: AABB) -> bool:
        """圆与矩形相交：找矩形上离圆心最近的点，判断距离。"""
        nearest_x = max(box.left, min(self.cx, box.right))
        nearest_y = max(box.top, min(self.cy, box.bottom))
        dx, dy = self.cx - nearest_x, self.cy - nearest_y
        return dx * dx + dy * dy <= self.r * self.r


class SpatialGrid:
    """空间网格：把大地图切成格子，只检测同格及相邻格的对象。

    对象上千时，把 O(n²) 降到接近 O(n)。
    """
    def __init__(self, cell_size=100):
        self.cell = cell_size
        self.buckets = {}

    def _key(self, x, y):
        return (int(x // self.cell), int(y // self.cell))

    def insert(self, obj, x, y):
        self.buckets.setdefault(self._key(x, y), []).append(obj)

    def nearby(self, x, y):
        """返回该位置所在格及周围 8 格里的对象。"""
        gx, gy = self._key(x, y)
        result = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                result.extend(self.buckets.get((gx + dx, gy + dy), []))
        return result


if __name__ == "__main__":
    a = AABB(0, 0, 10, 10)
    b = AABB(5, 5, 10, 10)
    c = AABB(20, 20, 5, 5)
    print("A 与 B 相交:", a.overlaps(b), "(应为 True)")
    print("A 与 C 相交:", a.overlaps(c), "(应为 False)")

    ball = Circle(12, 12, 3)
    print("圆 与 B 相交:", ball.overlaps_aabb(b), "(应为 True)")

    grid = SpatialGrid(cell_size=10)
    grid.insert("敌1", 3, 3)
    grid.insert("敌2", 33, 33)
    print("位置(4,4)附近对象:", grid.nearby(4, 4), "(应只有 敌1)")
