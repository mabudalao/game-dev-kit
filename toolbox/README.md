# 现成工具库（先找轮子，再造轮子）

原则：写新脚本前先在这里找。这里没有、且 GitHub 上确实找不到合适的，才自己写；自己写的那部分要在末节登记理由。

## 一、按用途分类

| 用途 | 轮子 | 星标 | 语言 | 能替掉我们脚本里的什么 |
|------|------|------|------|--------------------------|
| 高速抓屏 | [ra1nty/DXcam](https://github.com/ra1nty/DXcam) | 800 | Python |  Windows 毫秒级抓帧；备选 mss |
| 找图/模板匹配 | [NetEaseGame/aircv](https://github.com/NetEaseGame/aircv) | 387 | Python | **多尺度搜索 + NMS 去重 + 相关系数置信度**，替掉手写 RGB 绝对差和手调阈值（`INN_THR` / `GO_THR`） |
| 识别流水线 | [MaaXYZ/MaaFramework](https://github.com/MaaXYZ/MaaFramework) | 5.2k | C++ / JSON | **基准分辨率统一缩放（720p）** + 同目标多模板 + ROI+阈值 的工程范式，治“换分辨率就废” |
| 抗缩放匹配 | [prob1995/multi_scale_multi_object_template_matching](https://github.com/prob1995/multi_scale_multi_object_template_matching) | 24 | Python | ORB/SIFT 特征匹配，模板彻底失配时的兜底（慢，不当主路径） |
| 一站式游戏自动化 | [AirtestProject/Airtest](https://github.com/AirtestProject/Airtest) | 9.6k | Python | 截图 + 找图 + 点击 + 报告；不想自己拼装时的整体替代 |
| 文字识别 | [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR) | 8.6k | Python | 替掉或对照 WinRT OCR，中文更稳 |
| 截图即识字 | [hiroi-sora/Umi-OCR](https://github.com/hiroi-sora/Umi-OCR) | 48.9k | Python / QML | 离线 OCR 服务，可当外部识别后端 |
| 屏幕取字 | [TheJoeFin/Text-Grab](https://github.com/TheJoeFin/Text-Grab) | 5.1k | C# | Windows 原生 OCR 的成熟用法参考（与 `ocrlib.py` 同源） |
| 目标检测 | [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics) | 63.7k | Python | 图标 / 怪物检测，模板匹配不稳时的重量级方案 |
| 标注 / 基准集 | [wkentaro/labelme](https://github.com/wkentaro/labelme) | 16.3k | Python | 给截图打框建基准集，算真命中/误配率 |
| 识别调试台 | [kqcoxn/MaaPipelineEditor](https://github.com/kqcoxn/MaaPipelineEditor) | 432 | TypeScript | 可视化审阅、调识别、回归打分 |
| 画面相似度 | [jenssegers/imagehash](https://github.com/jenssegers/imagehash) 2060（PHP）、[coenm/ImageHash](https://github.com/coenm/ImageHash) 242（C#） | — | 感知哈希判“画面是否变了”，替掉逐像素累加对比 |

## 二、选择顺序

1. **能不能纯算法解决** —— 多尺度 / NMS / 相关系数，拄 aircv，不引库
2. **要认字** —— RapidOCR（进程内）或 Umi-OCR（本地服务）
3. **要跨分辨率稳定** —— 用 MaaFramework 的“基准分辨率统一缩放”范式
4. **模板彻底不稳** —— ORB/SIFT 兜底，最后才上 YOLO
5. **要判断识别好不好** —— labelme 标注 + 按 MaaPipelineEditor 形态打分

## 三、这些工具做不到的事

- 显示怪物血上限/攻/防/敏：战斗界面只有名字、等级和一根无数字的血条，任何读屏类工具都变不出这些数

## 四、自己写过的东西登记

| 文件 | 为什么没用现成轮子 |
|------|------------------|
| `frameworks/moli175/magic_loop.py` | 当时定了零第三方依赖 + 只在 Win32 里跑；算法部分后续可按 aircv 升级（尚未做） |
| `vision/vision_kit.py` | 通用骨架，允许 opencv，已经是 matchTemplate + 多尺度 + NMS 的写法 |
