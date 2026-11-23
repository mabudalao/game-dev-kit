# 游戏开发与脚本编写资料库

一个从零开始的游戏开发学习仓库，涵盖**游戏框架搭建**和**游戏脚本编写**两大块。
内容均为通用的、合法的游戏开发技术，不涉及任何游戏的破解、外挂或作弊。

## 目录结构

```
game-dev-kit/
├── frameworks/         游戏框架选型与搭建
│   ├── README.md       主流引擎/框架对比、适用场景、快速上手
│   └── turn_based.md   回合制游戏循环：设计骨架 + GitHub 优质项目清单
├── scripts/            游戏脚本编写
│   └── README.md       脚本架构、常用模式、设计规范
└── examples/           可直接运行的示例代码（纯 Python 标准库）
    ├── game_loop.py       固定时间步的游戏主循环
    ├── state_machine.py   游戏状态机（菜单/游玩/暂停/结束）
    ├── collision.py       2D 碰撞检测（AABB / 圆形）
    └── turn_based_battle.py  回合制战斗循环（行动队列 + 玩家/AI 统一调度）
```

## 从哪开始

1. 想选框架 → 看 [frameworks/README.md](frameworks/README.md)
2. 想学脚本架构 → 看 [scripts/README.md](scripts/README.md)
3. 想直接跑代码 → `python examples/game_loop.py`（无需安装第三方库）

## 核心概念速览

| 概念 | 说明 |
|------|------|
| 游戏循环 (Game Loop) | 输入 → 更新 → 渲染，固定时间步保证不同帧率下逻辑一致 |
| 状态机 (State Machine) | 管理菜单/战斗/暂停等场景切换，避免满屏 if-else |
| 实体组件 (ECS) | 组合优于继承，灵活组织游戏对象 |
| 碰撞检测 | AABB、圆形、空间划分（网格/四叉树）优化 |
| 回合调度 | 按速度排序的行动队列 + 行动状态机（见回合制示例） |
| 资源热更新 | 配置与代码分离，改数值不用重新打包 |

## 许可

本仓库示例代码可自由学习使用。
