# 屏幕识图（Vision）

目标：**在本地画面上准确、快速地找到目标，并读出文字**。
全部操作只发生在自己电脑的屏幕像素上，不读取游戏进程内存、不抓包、不修改游戏文件。

## 一、GitHub 上的可选件

| 项目 | 星标 | 语言 | 定位 | 拿来做什么 |
|------|------|------|------|-----------|
| [AirtestProject/Airtest](https://github.com/AirtestProject/Airtest) | 9.6k | Python | 游戏/App UI 自动化框架 | 一站式：截窗口 + aircv 找图 + 点击 + 报告，不想自己拼装就用它 |
| [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR) | 8.6k | Python | PaddleOCR 的轻量 ONNX 推理版 | 会变的文字（血量数字、物品名、对话），CPU 毫秒级 |
| [ra1nty/DXcam](https://github.com/ra1nty/DXcam) | 800 | Python | Desktop Duplication 高速抓屏 | 抓一帧几毫秒，解决"匹配不慢、抓屏慢"的瓶颈 |
| OpenCV `cv2.matchTemplate` | —— | C++/Python | 工业界标准模板匹配 | 固定 UI（按钮、血条、背包格）的基准方案 |

## 二、组合流程

```
DXcam 抓屏（只抓游戏窗口）
   → 裁 ROI（不要全屏搜，缩小搜索范围是最有效的提速手段）
   → 固定 UI：cv2 灰度多尺度 matchTemplate，阈值 0.85
   → 会变的文字：RapidOCR 只跑那一小块
   → 纯颜色状态（血条红/绿）：取区域平均色，比模板更省
```

## 三、快在哪

- **抓屏**：DXcam > mss > PIL/ImageGrab，差距在毫秒级 → 十毫秒级
- **灰度**：转灰度后匹配约快 3 倍，颜色只在判断状态时需要
- **ROI**：搜索面积减半，耗时就减半，比任何算法优化都直接
- **模板缓存**：模板只读一次，按文件 mtime 缓存
- **尺度**：单一分辨率只跑 `scale=1.0`；不确定就 (0.9, 1.0, 1.1) 三档

## 四、准在哪（这些坑不处理，换个分辨率就废）

- 模板必须和运行时**同分辨率、同缩放**截取；系统 DPI 125%/150% 会让坐标整体偏移 → 脚本里必须先 `SetProcessDpiAwareness`
- 窗口被拉伸或改尺寸 → 走多尺度，或干脆锁死窗口大小
- UI 半透明、呼吸动画 → 阈值降不到 0.75–0.8，再用"连续两帧命中"去伪
- 近似图标（同色不同物品）→ 提高模板信息量（截大一点、带边框），别只截图标中心
- 文字一定上 OCR，不要做模板

## 五、安装

```
pip install opencv-python numpy
pip install dxcam mss
pip install rapidocr-onnxruntime   # 需要 OCR 时
```

## 六、文件

- `vision_kit.py` —— 可直接 import 的工具库骨架
  - `grab(region)` 抓帧（dxcam → mss → PIL 自动降级）
  - `find()` / `find_all()` 多尺度模板匹配，返回屏幕绝对坐标
  - `pixel_color()` 区域平均色判断
  - `save_template()` 按当前尺度截模板，避免模板与运行时不一致
  - `wait_for()` 轮询等待目标出现
  - `read_text()` OCR
  - CLI：`python vision_kit.py shot` / `find npc.png` / `ocr`

`vision_kit.py` 已做语法校验；实际运行需先装 opencv，其余依赖缺哪个就自动降级或给明确报错。
