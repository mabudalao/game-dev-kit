# -*- coding: utf-8 -*-
"""一起玩魔力 自动循环（改进版，零第三方依赖）

流程骨架沿用参考脚本 magic_loop.py：
  野外自动遇敌练级 -> 累计 N 场查包，满包回城 -> 开地图找「冒险者旅馆」
  -> 前往进旅馆 -> 回放录制上二楼 -> 找绿字「魔石贩卖员」贴住全队出售
  -> 回城 -> 开地图点「练级传送石」回练级点进洞 -> 继续遇敌。

和参考脚本的差别（按本机实测对齐）：
  - 截图走 ctypes PrintWindow（mss 在这台 Unity 窗口上会黑帧/被遮挡抓不到）；
  - 不依赖 cv2 / pyautogui / pygetwindow / mss / numpy / keyboard，全用纯 Win32 +
    WinRT OCR + 现有实测模块；
  - 模板/识字按实测口径：固定图标走抓图匹配，按钮文字/菜单选项才 OCR；
  - 上楼、传送后走位、二楼巡逻都回放已录制的宏（比例坐标，按原节奏）。

用法：
  python magic_loop.py            完整循环
  python magic_loop.py map        只测：回城 -> 冒险者旅馆 -> 上二楼
  python magic_loop.py sell2f     当前站二楼：巡逻找 NPC -> 全队出售 -> 回城
  python magic_loop.py level      只测：回城 -> 练级传送石 -> 回点进洞

热键：F8 暂停/继续，F9 退出。
"""

import json
import os
import sys
import time
import traceback

sys.dont_write_bytecode = True

# 控制台/重定向日志是 GBK：日志里出现 ✓ 这类字符会抛 UnicodeEncodeError，直接把整个循环打死
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

import moli_auto as m
import _flow as f
import _step1 as s1
import _greens as g
import _npc_go as npc
import ocrlib
import pngio

HERE = os.path.dirname(os.path.abspath(__file__))

# ============ 可调参数 ============
CFG = {
    "bag_interval": 15 * 60,     # 每多少秒查一次包（15 分钟）
    "up_macro": "inn_up2.json",  # 上楼录制
    "tp_macro": "tp_click2.json",  # 传送石旁：点传送石唤面板 -> 选练级点 -> 传送
    "go_macro": "tp_go2.json",     # 回城后：开图/拖图/点传送石/点前往
    "tp_wait": 12.0,               # 传送确认后等落地（秒）
    "in_macro": "fuleya_cave2.json",  # 芙蕾亚落点走到狗洞并进洞的走位录制（新录 10 点/24.6s）
    "use_in_macro": True,         # 回放芙蕾亚→狗洞走位宏
    "roam_macro": "npc_roam3.json",  # 二楼巡逻录制（73点/20段，x0.21-0.75 覆盖左右边缘；roam4 范围窄有盲区）
    "roam_every": 2,             # 巡逻每几个动作扫一次绿字
    "roam_speed": 1.0,
    "inn_timeout": 180.0,        # 等走进旅馆的兜底上限（秒）；到位/卡住由移动检测判定
    "lvl_wait": 45.0,            # 传送后等到位的超时（秒）
}

TOGGLE_VK = 0x77   # F8
QUIT_VK = 0x78     # F9
state = {"run": True, "quit": False}
_prev = {}


PANEL_CMD_FILE = os.path.join(HERE, "_panel_cmd.txt")


def _panel_cmd():
    """读桌面面板写下的指令文件（pause / resume / quit），读完即删。"""
    try:
        if not os.path.exists(PANEL_CMD_FILE):
            return None
        with open(PANEL_CMD_FILE, encoding="utf-8") as fp:
            cmd = (fp.read() or "").replace("\ufeff", "").strip().lower()   # 容忍面板旧版带 BOM
        try:
            os.remove(PANEL_CMD_FILE)
        except Exception:
            pass
        return cmd
    except Exception:
        return None


def hotkeys():
    for vk, kind in ((TOGGLE_VK, "run"), (QUIT_VK, "quit")):
        down = bool(m.user32.GetAsyncKeyState(vk) & 0x8000)
        if down and not _prev.get(vk):
            if kind == "run":
                state["run"] = not state["run"]
                log("已暂停" if not state["run"] else "继续")
            else:
                state["quit"] = True
                log("热键退出")
        _prev[vk] = down
    # 面板按钮
    cmd = _panel_cmd()
    if cmd:
        if cmd in ("pause", "paused", "暂停"):
            if state["run"]:
                state["run"] = False
                log("面板：暂停")
        elif cmd in ("resume", "run", "start", "继续", "开始"):
            if not state["run"]:
                state["run"] = True
                log("面板：继续")
        elif cmd in ("quit", "exit", "stop", "退出", "停止"):
            state["quit"] = True
            log("面板：退出")


def log(msg):
    print(time.strftime("[%H:%M:%S] "), msg, flush=True)


def tick():
    hotkeys()
    if state["quit"]:
        raise SystemExit
    while not state["run"] and not state["quit"]:
        time.sleep(0.1)
        hotkeys()


def _focus_game(h):
    """把游戏窗口切到前台。set_auto 有前台门禁：不在前台它一下都不点，只返回失败。"""
    if m.is_foreground(h):
        return True
    try:
        m.user32.keybd_event(0x12, 0, 0, 0)      # 按一下 ALT，解锁前台切换
        m.user32.keybd_event(0x12, 0, 2, 0)
        time.sleep(0.05)
        m.user32.SetForegroundWindow(m.wt.HWND(h))
        time.sleep(0.4)
    except Exception as e:
        log("  切前台出错: %r" % e)
    return m.is_foreground(h)


def _set_auto(h, want):
    """点/关野外遇敌：先切前台，再按真实结果记日志。

    原来直接调 m.set_auto 而且不看返回值：窗口在后台时它一次都不点、返回失败，
    循环却照样写“点一次遇敌”，日志和实际动作对不上（2026-11-20 04:13 就是这样空转）。
    """
    fg = _focus_game(h)
    r = m.set_auto(h, want)
    if not r.get("ok"):
        log("  set_auto(%s) 失败%s：%s"
            % (want, "" if fg else "（窗口切不到前台）", r.get("reason")))
    return r


# ============ 通用回放 ============

def play_macro(h, name, speed=1.0, start=0.0, ui_filter=True, battle_pause=False, on_step=None):
    path = name if name.lower().endswith(".json") else os.path.join(HERE, name)
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    ev = [e for e in data.get("events", []) if e["t"] >= start]
    if not ev:
        log("  宏里没有动作: %s" % name)
        return False
    cw, ch = m.client_size(h)
    t0, wall = ev[0]["t"], time.time()
    for e in ev:
        tick()
        if battle_pause:
            # 走位路上遇敌：暂停回放，等打完回到野外再继续剩余走位点
            if m.in_battle(h):
                log("  走位中进战斗，等打完再继续")
                if not m._wait_field(h, timeout=90):
                    log("  战斗超时未回野外，中断走位宏")
                    return False
                time.sleep(0.8)
                # 等待期间墙钟已走，重置时间基准，否则剩余事件被压缩成瞬间连发点在原地
                wall = time.time()
                t0 = e["t"]
            elif m.ui_layout(h) is None:
                time.sleep(1.0)
        gap = (e["t"] - t0) * speed - (time.time() - wall)
        if gap > 0:
            time.sleep(gap)
        x, y = int(round(e["x"] * cw)), int(round(e["y"] * ch))
        if e["type"] != "key" and ui_filter and npc.in_ui(x, y, cw, ch):
            continue   # 点击/滚轮落在按钮区一律不点；菜单传送宏回放 ui_filter=False 不过滤
        if e["type"] == "click":
            m.click_client(h, x, y, button=e.get("button", "left"))
        elif e["type"] == "drag":
            x2 = int(round(e["x2"] * cw))
            y2 = int(round(e["y2"] * ch))
            f._drag(h, x, y, x2 - x, y2 - y)
        elif e["type"] == "key":
            m.tap_key(e["vk"])
        elif e["type"] == "wheel":
            m.wheel(1 if e.get("delta", 1) > 0 else -1)
        # 走位宏专用：每点完一步，等画面稳住再扫一次（扫到东西 on_step 返回 True 就中断回放）
        if on_step is not None and e["type"] in ("click", "drag"):
            time.sleep(1.5)
            if on_step(e):
                return "found"
    return True


# ============ 段：回城 ============

_CITY_KEYS = ("城", "镇", "村")


def _is_city(txt):
    """地名像城镇吗：含「城/镇/村」且不含「洞/窟」。读空一律当“不是城里”。"""
    if not txt:
        return False
    if ("洞" in txt) or ("窟" in txt):
        return False
    return any(k in txt for k in _CITY_KEYS)


def _confirm_home(h):
    """点完回城图标后：直接点「确定」→ 判「法兰城」。

    确认框实测是**深紫底 + 淡金边**（不是米黄），框里那行字 OCR 基本读不出，
    米黄/金色两类像素判据实测占比都是 0，所以不再试图"判框"——
    点完回城图标等 0.6 秒，直接点一次「确定」按钮的位置：
      - 弹框在  → 正好点中「确定」，回城成功
      - 没弹框  → 点到地面，角色走一小步，无副作用（进旅馆会重新寻路）
    按钮本身约 90×30，「确定」中心实测整窗 (549,362) → 客户区 (541,331)。
    """
    cw, ch = m.client_size(h)
    time.sleep(0.6)
    m.click_client(h, int(m.HOME_OK_REL[0] * cw), int(m.HOME_OK_REL[1] * ch), src="回城确定")
    time.sleep(2.0)
    city = m.wait_message(h, m.HOME_CITY_NEEDLES, timeout=6)
    return bool(city)
