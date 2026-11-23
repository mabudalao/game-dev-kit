# -*- coding: utf-8 -*-
"""
vision_kit.py —— 屏幕识图工具骨架（Windows，纯本地）

只做三件事：抓屏、在本地画面里找图、在本地画面里读字。
不读取游戏进程内存、不抓包、不修改任何游戏文件。

依赖（按需安装，缺少时自动降级或给出明确报错）：
    pip install opencv-python numpy     # 必需：模板匹配
    pip install dxcam                    # 推荐：高速抓屏（Desktop Duplication）
    pip install mss                      # 备用：抓屏
    pip install rapidocr-onnxruntime      # 可选：文字识别

用法示例：
    python vision_kit.py shot                  # 截全屏存 shot.png
    python vision_kit.py find npc.png 0.85     # 在全屏里找模板
    python vision_kit.py ocr                   # 全屏 OCR
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("缺少 opencv-python，请先执行：pip install opencv-python numpy") from exc


Region = Tuple[int, int, int, int]  # (left, top, right, bottom)


# ---------------------------------------------------------------- DPI 感知
def _enable_dpi_awareness() -> None:
    """让截图坐标等于物理像素，避免系统缩放 125%/150% 时点击整体偏移。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()


# ---------------------------------------------------------------- 抓屏
_cam = None
_cam_failed = False


def _grab_dxcam(region: Optional[Region]) -> Optional[np.ndarray]:
    global _cam, _cam_failed
    if _cam_failed:
        return None
    try:
        if _cam is None:
            import dxcam  # noqa: WPS433

            _cam = dxcam.create(output_color="BGR")
        for _ in range(4):
            frame = _cam.grab(region=region)
            if frame is not None:
                return frame
            time.sleep(0.005)
        return None
    except Exception:
        _cam_failed = True
        return None


def _grab_mss(region: Optional[Region]) -> Optional[np.ndarray]:
    try:
        import mss  # noqa: WPS433

        with mss.mss() as sct:
            if region is None:
                mon = sct.monitors[1]
                box = {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}
            else:
                box = {
                    "left": region[0],
                    "top": region[1],
                    "width": region[2] - region[0],
                    "height": region[3] - region[1],
                }
            raw = np.asarray(sct.grab(box))
            return raw[:, :, :3].copy()  # BGRA -> BGR
    except Exception:
        return None


def _grab_pil(region: Optional[Region]) -> np.ndarray:
    from PIL import ImageGrab  # noqa: WPS433

    bbox = None if region is None else tuple(region)
    img = ImageGrab.grab(bbox=bbox)
    rgb = np.asarray(img)[:, :, :3]
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def grab(region: Optional[Region] = None) -> np.ndarray:
    """抓一帧，返回 BGR ndarray。优先 dxcam，其次 mss，最后 PIL。"""
    frame = _grab_dxcam(region)
    if frame is not None:
        return frame
    frame = _grab_mss(region)
    if frame is not None:
        return frame
    return _grab_pil(region)


# ---------------------------------------------------------------- 匹配
@dataclass
class Match:
    score: float
    left: int
    top: int
    width: int
    height: int

    @property
    def center(self) -> Tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2

    def __repr__(self) -> str:  # 方便打印日志
        cx, cy = self.center
        return f"Match(score={self.score:.3f}, center=({cx},{cy}), box={self.width}x{self.height})"


_tpl_cache: dict = {}


def load_template(path: str, grayscale: bool = True) -> np.ndarray:
    """加载模板图并缓存。模板必须与运行时同分辨率同缩放截取。"""
    abspath = os.path.abspath(path)
    key = (abspath, os.path.getmtime(abspath), grayscale)
    cached = _tpl_cache.get(key)
    if cached is not None:
        return cached
    flag = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
    tpl = cv2.imread(abspath, flag)
    if tpl is None:
        raise FileNotFoundError(f"模板读取失败：{abspath}")
    _tpl_cache[key] = tpl
    return tpl


def _prepare(frame: np.ndarray, grayscale: bool) -> np.ndarray:
    if not grayscale:
        return frame
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def find(
    template_path: str,
    region: Optional[Region] = None,
    threshold: float = 0.85,
    scales: Sequence[float] = (1.0,),
    grayscale: bool = True,
    frame: Optional[np.ndarray] = None,
    method: int = cv2.TM_CCOEFF_NORMED,
) -> Optional[Match]:
    """在给定区域（或整屏）内做多尺度模板匹配，返回分数最高且过阈值的结果。

    scales 建议按需给 (0.8, 0.9, 1.0, 1.1, 1.2)，单一分辨率下只传 (1.0,) 最快。
    """
    screen = _prepare(frame if frame is not None else grab(region), grayscale)
    tpl = load_template(template_path, grayscale=grayscale)
    offset_x, offset_y = (region[0], region[1]) if region else (0, 0)

    best: Optional[Match] = None
    for scale in scales:
        if abs(scale - 1.0) < 1e-6:
            scaled = tpl
        else:
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            scaled = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=interp)
        if scaled.shape[0] > screen.shape[0] or scaled.shape[1] > screen.shape[1]:
            continue  # 模板比搜索区域还大，跳过
        result = cv2.matchTemplate(screen, scaled, method)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if best is None or max_val > best.score:
            best = Match(
                score=float(max_val),
                left=int(max_loc[0]) + offset_x,
                top=int(max_loc[1]) + offset_y,
                width=int(scaled.shape[1]),
                height=int(scaled.shape[0]),
            )
    if best is None or best.score < threshold:
        return None
    return best


def find_all(
    template_path: str,
    region: Optional[Region] = None,
    threshold: float = 0.85,
    scales: Sequence[float] = (1.0,),
    grayscale: bool = True,
    max_items: int = 10,
    frame: Optional[np.ndarray] = None,
) -> List[Match]:
    """找出所有过阈值的实例（迭代抑制，适合背包格子、怪物列表等重复元素）。"""
    screen = _prepare(frame if frame is not None else grab(region), grayscale)
    tpl = load_template(template_path, grayscale=grayscale)
    offset_x, offset_y = (region[0], region[1]) if region else (0, 0)

    matches: List[Match] = []
    for scale in scales:
        scaled = tpl if abs(scale - 1.0) < 1e-6 else cv2.resize(
            tpl, None, fx=scale, fy=scale,
            interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
        )
        if scaled.shape[0] > screen.shape[0] or scaled.shape[1] > screen.shape[1]:
            continue
        result = cv2.matchTemplate(screen, scaled, cv2.TM_CCOEFF_NORMED)
        work = result.copy()
        for _ in range(max_items - len(matches)):
            _, max_val, _, max_loc = cv2.minMaxLoc(work)
            if max_val < threshold:
                break
            matches.append(
                Match(
                    score=float(max_val),
                    left=int(max_loc[0]) + offset_x,
                    top=int(max_loc[1]) + offset_y,
                    width=int(scaled.shape[1]),
                    height=int(scaled.shape[0]),
                )
            )
            # 抑制已匹配区域，避免同一个目标被反复命中
            x0 = max(0, max_loc[0] - scaled.shape[1] // 2)
            y0 = max(0, max_loc[1] - scaled.shape[0] // 2)
            x1 = min(work.shape[1], max_loc[0] + scaled.shape[1] // 2 + 1)
            y1 = min(work.shape[0], max_loc[1] + scaled.shape[0] // 2 + 1)
            work[y0:y1, x0:x1] = -1.0
    return matches


def pixel_color(region: Region, frame: Optional[np.ndarray] = None) -> Tuple[int, int, int]:
    """取区域平均色（BGR），用于判断血条红/绿等状态，比模板更省时间。"""
    img = frame if frame is not None else grab(region)
    mean = img.reshape(-1, img.shape[-1]).mean(axis=0)
    return int(mean[0]), int(mean[1]), int(mean[2])


def save_template(name: str, region: Region, out_dir: str = "templates") -> str:
    """按当前分辨率截取一块区域存成模板图，保证模板与运行时同尺度。"""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.png")
    cv2.imwrite(path, grab(region))
    return path


def wait_for(
    template_path: str,
    region: Optional[Region] = None,
    threshold: float = 0.85,
    timeout: float = 10.0,
    interval: float = 0.2,
) -> Optional[Match]:
    """轮询等待画面出现目标，超时返回 None。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        m = find(template_path, region=region, threshold=threshold)
        if m is not None:
            return m
        time.sleep(interval)
    return None


# ---------------------------------------------------------------- OCR
@dataclass
class TextItem:
    text: str
    score: float
    left: int
    top: int


_ocr_engine = None


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR  # noqa: WPS433

        _ocr_engine = RapidOCR()
    return _ocr_engine


def read_text(
    region: Optional[Region] = None,
    frame: Optional[np.ndarray] = None,
    min_score: float = 0.5,
) -> List[TextItem]:
    """识别区域内的文字。只对会变化的文本使用（数字、物品名、对话）。"""
    ocr = _get_ocr()
    img = frame if frame is not None else grab(region)
    result, _ = ocr(img)
    items: List[TextItem] = []
    offset_x, offset_y = (region[0], region[1]) if region else (0, 0)
    for box, text, score in result or []:
        if float(score) < min_score:
            continue
        xs = [pt[0] for pt in box]
        ys = [pt[1] for pt in box]
        items.append(
            TextItem(
                text=str(text),
                score=float(score),
                left=int(min(xs)) + offset_x,
                top=int(min(ys)) + offset_y,
            )
        )
    return items


# ---------------------------------------------------------------- CLI
def _main(argv: Iterable[str]) -> int:
    args = list(argv)
    if not args:
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "shot":
        out = args[1] if len(args) > 1 else "shot.png"
        cv2.imwrite(out, grab())
        print(f"已保存：{os.path.abspath(out)}")
        return 0
    if cmd == "find" and len(args) >= 2:
        threshold = float(args[2]) if len(args) > 2 else 0.85
        match = find(args[1], threshold=threshold, scales=(0.9, 1.0, 1.1))
        print(match if match else "未找到（低于阈值）")
        return 0
    if cmd == "ocr":
        for item in read_text():
            print(f"{item.score:.2f}\t({item.left},{item.top})\t{item.text}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
