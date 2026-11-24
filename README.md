# 游戏开发与脚本编写资料库

一个从零开始的游戏开发学习仓库，涵盖**游戏框架搭建**、**游戏脚本编写**、**本地屏幕识图与自动化**三块，并收录一套已实跑过的实战框架与一份现成工具库索引。
内容均为通用的、合法的游戏开发技术，不涉任何游戏的破解、外挂或作弊。

## 目录结构

```
game-dev-kit/
├── toolbox/            现成工具库索引（写脚本前先来这里找）
│   └── README.md       抓屏/找图/OCR/标注/目标检测 分类清单 + 选择顺序
├── frameworks/         游戏框架选型与搭建
│   ├── README.md       主流引擎/框架对比、适用场景、快速上手
│   ├── turn_based.md   回合制游戏循环：设计骨架 + GitHub 优质项目清单
│   └── moli175/        175魔力：实跑过的回合制客户端自动化框架
│       ├── README.md   循环骨架、7 个可借鉴设计点、四段已验证状态、已知卡点
│       └── magic_loop.py   主脚本 1617 行 / 66 KB，零第三方依赖
├── scripts/            游戏脚本编写
│   └── README.md       脚本架构、常用模式、设计规范
├── vision/             本地屏幕识图（只看自己屏幕像素）
│   ├── README.md       Airtest / RapidOCR / DXcam / OpenCV 选型，提速与准确要点
│   └── vision_kit.py   抓屏 + 多尺度模板匹配 + 取色 + OCR（dxcam→mss→PIL 自动降级）
├── automation/         本地客户端自动化
│   └── README.md       边界（不碰服务器）、状态机骨架、安全阀、开发顺序
└── examples/           可直接运行的示例代码（纯 Python 标准库）
    ├── game_loop.py       固定时间步的游戏主循环
    ├── state_machine.py   游戏状态机（菜单/游玩/暂停/结束）
    ├── collision.py       2D 碰撞检测（AABB / 圆形）
    └── turn_based_battle.py  回合制战斗循环（行动队列 + 玩家/AI 统一调度）
```

## 从哪开始

1. 要写新脚本 → 先看 [toolbox/README.md](toolbox/README.md)，能复用就不自己写
2. 想选框架 → 看 [frameworks/README.md](frameworks/README.md)
3. 想学脚本架构 → 看 [scripts/README.md](scripts/README.md)
4. 想直接跑代码 → `python examples/game_loop.py`（无需安装第三方库）
5. 想做屏幕识图 → 看 [vision/README.md](vision/README.md)，需要 `pip install opencv-python`
6. 想做本地自动化 → 看 [automation/README.md](automation/README.md)，先读“明确不做的”
7. 想看实战完整循环 → 看 [frameworks/moli175/README.md](frameworks/moli175/README.md)

## 核心概念速览

| 概念 | 说明 |
|------|------|
| 游戏循环 (Game Loop) | 输入 → 更新 → 渲染，固定时间步保证不同帧率下逻辑一致 |
| 状态机 (State Machine) | 管理菜单/战斗/暂停等场景切换，避免满屏 if-else |
| 实体组件 (ECS) | 组合优于继承，灵活组织游戏对象 |
| 碰撞检测 | AABB、圆形、空间划分（网格/四叉树）优化 |
| 回合调度 | 按速度排序的行动队列 + 行动状态机（见回合制示例） |
| 资源热更新 | 配置与代码分离，改数值不用重新打包 |
| 模板匹配 | `cv2.matchTemplate` + 灰度 + ROI + 多尺度，固定 UI 的基准方案 |
| 基准分辨率 | 截图先缩到固定尺寸再识别，模板只需按基准截一次（MaaFramework 范式） |
| 屏幕 OCR | RapidOCR（ONNX 推理），CPU 毫秒级，处理会变的文字 |
| 三态判定 | 识别结果分 True/False/None，读不出就不动手（见 moli175） |

## 许可

本仓库示例代码可自由学习使用。
