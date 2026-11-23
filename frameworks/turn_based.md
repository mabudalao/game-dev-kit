# 回合制游戏循环（Turn-Based Loop）

回合制和实时游戏的核心区别：**没有"每帧更新"的紧迫感，而是"轮到谁 → 他行动 → 轮到下一个"的离散推进。**
实时游戏用固定时间步（`examples/game_loop.py`），回合制游戏用**回合调度器 + 状态机**。

## 一、回合制循环的骨架

```
       ┌─────────────────────────────────┐
       │  战斗开始：按速度/先攻排序出行动序列  │
       └────────────────┬────────────────┘
                        ▼
   ┌──────────────────────────────────────────┐
   │  当前行动者 = 队列头                        │
   │    ├─ 玩家 → 等待输入（选攻击/技能/道具）      │
   │    └─ AI   → 自动决策                       │
   └────────────────┬─────────────────────────┘
                    ▼
        执行行动 → 结算伤害/状态 → 播放动画
                    ▼
        判定胜负？ ──否──> 该单位进入队尾，下一轮
           │是
           ▼
        战斗结束
```

关键设计：
- **行动队列（Turn Order）**：按速度排序，每轮结束把行动者重新插入队列（可用速度值算位置，实现"速度快的行动更频繁"）
- **行动状态机**：`选择指令 → 选择目标 → 执行 → 结算 → 交还控制权`
- **等待玩家输入 vs AI 决策**：玩家回合挂起等输入，AI 回合自动跑，两者走同一套"执行行动"逻辑

## 二、GitHub 上值得参考的开源项目

| 项目 | 星标 | 语言 | 许可 | 看点 |
|------|------|------|------|------|
| [Brackeys/Turn-based-combat](https://github.com/Brackeys/Turn-based-combat) | 120 | C# | 无 | Unity 官方教程级实现，从零讲回合制战斗，最适合入门 |
| [soonfx-engine/core](https://github.com/soonfx-engine/core) | 714 | TypeScript | Apache-2.0 | 中文项目，RPG/策略数值引擎，公式解析+战斗模拟，设计值得读 |
| [Bozar/godot-4-roguelike-tutorial](https://github.com/Bozar/godot-4-roguelike-tutorial) | 68 | GDScript | MIT | Godot 4 回合制 Roguelike，逐帧教程，回合调度清晰 |
| [LecodeMV/leTBS](https://github.com/LecodeMV/leTBS) | 52 | JavaScript | 自定义 | RPG Maker MV 战棋战术战斗系统，格子+回合+AI |
| [kimimaru4000/PaperMarioBattleSystem](https://github.com/kimimaru4000/PaperMarioBattleSystem) | 41 | C# | Unlicense | 复刻纸片马里奥回合制，含行动指令与反馈系统设计 |
| [SunnyValleyStudio/make-civilization-in-unity](https://github.com/SunnyValleyStudio/make-civilization-in-unity) | 9 | C# | - | 回合制策略（文明类）教程，适合学"大回合"调度 |

> 上面 are 参考其**设计思路**，注意各自的许可证，商用前看清条款。

## 三、回合制 vs 实时的循环对比

| 维度 | 实时（game_loop.py） | 回合制 |
|------|---------------------|--------|
| 推进单位 | 每一帧 (dt) | 每一个行动/回合 |
| 核心结构 | 固定时间步累加器 | 行动队列 + 状态机 |
| 时间控制 | delta time 决定速度 | 行动次数决定进度 |
| 玩家交互 | 连续输入（按住移动） | 离散指令（选菜单） |
| 典型场景 | 动作、射击、竞速 | RPG、战棋、卡牌、Roguelike |

## 四、可运行示例

见 `../examples/turn_based_battle.py` —— 纯 Python 标准库，演示：
- 按速度排序的行动队列
- 玩家回合 / AI 回合统一调度
- 攻击/防御/技能指令
- 胜负判定与循环推进

运行：`python examples/turn_based_battle.py`
