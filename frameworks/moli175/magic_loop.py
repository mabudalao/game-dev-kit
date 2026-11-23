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


def go_home(h):
    """点回城图标 → 有确认框就点确定 → **用地名验收**是否真的回到城里。

    回城的前提是**遇敌关闭**，不是“不在战斗”：
    战斗界面里根本没有回城按钮，遇敌开着就会一直被拖进战斗。12:04 那次就是
    满包冷启动直接走卖货，人在战斗里点 (787,124)，等于点在空气上。
    关遇敌只有一条路：进战斗 → 战斗内点「停止」→ 等战斗结束 → 等 10 秒确认不再遇敌。

    老问题（12:04 那次）：确认框没捕到，代码用「回城已点过两次，按成功算」放行，
    人其实还在洞里，后面开图找不到旅馆，只能固定点兜底，50 秒超时死循环。
    现在改成只认地名：读到「城/镇/村」才算成功；读到「洞/窟」或读不出，一律算没成，
    重点一次回城，最多 3 次；3 次都不成返回 False，让上层停下报错，绝不硬走。
    """
    log("回城")

    # 前提：遇敌必须是关着的
    r = m.stop_hunt(h)
    if not r.get("ok"):
        log("  遇敌没关掉（%s），再试一次" % r.get("why"))
        r = m.stop_hunt(h)
    if not r.get("ok"):
        log("  遇敌仍关不掉（%s），本次不点回城" % r.get("why"))
        return False
    log("  遇敌已关（%s）" % r.get("why"))

    # 点回城 -> 点确定 -> 直接进下一步。**不做地名验收**（用户定：回城键位置固定，
    # 点完就走，不再拿 OCR 结果决定要不要重复点）。
    cw, ch = m.client_size(h)
    m.click_client(h, *f.HOME_KEY)
    time.sleep(0.9)
    m.click_client(h, int(m.HOME_OK_REL[0] * cw), int(m.HOME_OK_REL[1] * ch), src="回城确定")
    time.sleep(2.2)
    log("  回城已点（不验收，直接下一步）")
    return True


# ============ 段：地图找冒险者旅馆 -> 前往 -> 进旅馆 ============

# 旅馆在法兰城东北象限（东门旁、练级传送石左上）。鼠标往左下拖，地图左下带、视野朝右上翻。
INN_DRAGS = [(-120, 90), (-120, 90), (-120, 90), (-120, 90)]
# 固定视野（法兰城城区实景）实测：可点的是旅馆金字标签中心，不是左侧房子图标（图标弹「目标不可到达」）
INN_LABEL = (407, 231)    # 客户区：旅馆金字标签中心
INN_GO = (402, 159)       # 客户区：气泡「前往」按钮中心


def _place_full(h, tag):
    """全图 OCR 拼地名（裁剪坐标条在深色底上读空率高，全图更稳）。"""
    m.grab_window_png(h, tag + ".png")
    try:
        return "".join(l["norm"] for l in ocrlib.lines(tag + ".png", scale=4))
    except Exception:
        return ""


def _center_block(h, half=70):
    """抓客户区中部人物区像素块（BGRA bytes），用于相邻帧判断人物是否在移动。"""
    g = m._grab(h)
    if not g:
        return None
    w, hgt, data, _, _ = g
    cx, cy = w // 2, hgt // 2
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(w, cx + half), min(hgt, cy + half)
    out = bytearray()
    for y in range(y0, y1):
        out += data[(y * w + x0) * 4:(y * w + x1) * 4]
    return bytes(out)


def _block_diff(a, b):
    """两块像素差异计数（超过色差阈值的像素个数）；块缺失返回很大值。"""
    if not a or not b or len(a) != len(b):
        return 10 ** 9
    d = 0
    for i in range(0, len(a), 4):
        if abs(a[i] - b[i]) + abs(a[i + 1] - b[i + 1]) + abs(a[i + 2] - b[i + 2]) > 30:
            d += 1
    return d


def _bubble_go(h, hit, tag):
    """点旅馆标签后，在气泡区定位「前往」按钮：模板找图优先，OCR 兜底，返回客户区坐标。"""
    m.grab_window_png(h, tag + ".png")
    go = match_go(tag + ".png")
    if go:
        # 落点取模板框上 1/3（按钮文字在上半部，取中心会压到下沿边框），再转客户区。
        return (go["x"] + go["w"] // 2 - 8, go["y"] + go["h"] // 3 - 31)
    igx, igy = hit["x"], hit["y"]
    for box in [(igx - 160, igy + 10, 380, 230), (igx - 160, igy - 240, 380, 230)]:
        X0, Y0, W, H = box
        X0 = max(0, X0)
        Y0 = max(0, Y0)
        if Y0 + H > 570:
            Y0 = max(0, 570 - H)
        g._crop_raw(tag + ".png", X0, Y0, W, H, out=tag + "z.png")
        rows = ocrlib.lines(tag + "z.png", scale=6)
        for r in rows:
            if "前往" in r["text"].replace(" ", ""):
                return (X0 + r["x"] + r["w"] // 2 - 8,
                        Y0 + r["y"] + r["h"] // 2 - 31)
    return None


# 地图面板顶部金线：y=72 那一行是固定 UI 美术，颜色实测恒为 (147,135,108)
MAP_GOLD = (147, 135, 108)
MAP_GOLD_TOL = 14
MAP_GOLD_XS = list(range(180, 801, 40))     # 17 个采样点，横跨整个面板宽度


def _gold_hits(get_rgb):
    """在 y=72 那行采样，数命中金线的点数。get_rgb(x, y) -> (r,g,b)。"""
    n = 0
    for x in MAP_GOLD_XS:
        r, g, b = get_rgb(x, 72)
        if (abs(r - MAP_GOLD[0]) <= MAP_GOLD_TOL
                and abs(g - MAP_GOLD[1]) <= MAP_GOLD_TOL
                and abs(b - MAP_GOLD[2]) <= MAP_GOLD_TOL):
            n += 1
    return n


def _map_is_open(h, tag):
    """判地图是否开着：只看面板顶部那条金线（像素判据，不 OCR）。

    实测 8 张截图：地图开着 17/17 命中，关着 0~1/17，分得很开。
    原来走 f.map_open 读「世界地图」四个字，OCR 在画面切换那一帧会读空，
    于是判成“没开”→ 不点关图 → 地图留在打开状态 → 后面全乱（2026-11-20 整夜空转的起因）。
    """
    try:
        g = m._grab(h)
        if not g:
            return False
        W, H, data = g[0], g[1], g[2]

        def px(x, y):
            i = (y * W + x) * 4
            return data[i + 2], data[i + 1], data[i]      # BGRA -> RGB

        return _gold_hits(px) >= len(MAP_GOLD_XS) * 0.8
    except Exception:
        return False


INN_MACRO = "inn_walk2.json"    # 录制：回城 -> 确定 -> 开图 -> 拖地图 -> 点旅馆 -> 点前往
INN_WALK_WAIT = 55.0            # 点完「前往」后的寻路时间（实测约 49.17 秒，按 55 算）
FULL_SPACE = 0                  # 用户定（2026-11-20）：空位 = 0 全满才算满 → 宁可多打几局，反正有经验
NOT_FULL_SPACE = 1              # （配上面那条）有空位就先去练级
FULL_SPACE_LOOP = 0             # 挂机中定时查包也用同一条线：空位 = 0 才算满 → 回城卖货


def _hunt_off(h):
    """回城前必须关遇敌：回城按钮只能在非遇敌状态点。"""
    r = m.stop_hunt(h)
    if not r.get("ok"):
        log("  遇敌没关掉（%s），再试一次" % r.get("why"))
        r = m.stop_hunt(h)
    if not r.get("ok"):
        log("  遇敌仍关不掉（%s）" % r.get("why"))
        return False
    log("  遇敌已关（%s）" % r.get("why"))
    return True


def enter_inn(h, tries=1):
    """按录制固定动作执行：回城 -> 到达冒险者旅馆 -> 关图。

    整段回放，不做任何识别（不找字、不判楼层、不判到达）。
    """
    log("回放录制：回城 -> 前往冒险者旅馆（%s）" % INN_MACRO)
    ok = play_macro(h, INN_MACRO, ui_filter=False)
    if not ok:
        log("  录制回放失败")
        return False
    log("  等 %.2f 秒（录制里的寻路时间，原样照搬）" % INN_WALK_WAIT)
    time.sleep(INN_WALK_WAIT)
    # 地图不会自己关：先点一次 X 关掉（坐标取自旧录制本人那一下 802,66）
    log("  点关图 (802,66)")
    m.click_client(h, 802, 66)
    time.sleep(0.8)
    log("  寻路时间到 + 关图 -> 接上二楼")
    return True


# ============ 段：上二楼 ============

def _is_2f(txt):
    """二楼判据：先排除三楼(3楼/三楼)；一楼地名「冒险者旅馆」不含楼层数字。
    兼容 OCR 漏读：2楼/二楼/单读「2」/误读龙楼/含楼，都算二楼。"""
    if ("3楼" in txt) or ("三楼" in txt):
        return False
    return ("2楼" in txt) or ("二楼" in txt) or ("2" in txt) or ("楼" in txt)


def _is_3f(txt):
    return ("3楼" in txt) or ("三楼" in txt)


def upstairs(h):
    """回放录制上二楼：走完直接下一步（不判楼层）。"""
    log("回放录制上二楼（不判楼层，走完直接卖）")
    play_macro(h, CFG["up_macro"])
    time.sleep(1.5)
    return True


# ============ 段：二楼找魔石贩卖员 -> 全队出售 ============

def try_sell_walk(h, max_rounds=6):
    """外层包一层急停保护：F9 一按，所有还没发出的点击立刻作废。"""
    try:
        return _try_sell_walk(h, max_rounds)
    except m.EStop:
        log("  [急停] 收到 F9，已停止全部点击")
        return {"ok": False, "why": "F9 急停"}


def _is_moving(h, thresh=2.6, gap=0.35):
    """抓两帧比中央区域，判断人物是不是正在走。"""
    a = npc._center_sig(h)
    time.sleep(gap)
    b = npc._center_sig(h)
    if not a or not b or len(a) != len(b):
        return False
    d = sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))
    return d >= thresh


def _try_sell_walk(h, max_rounds=6):
    """简化巡逻找 NPC → 点名字下70像素一次 → 等10秒判定。

    没弹菜单就接着往下走点，换个站位再识别再点一次；不原地连点。
    """
    pos = 0
    # 点击档位：0=名字下70  1=名字下30  2=名字本体
    # 规则：点完人动 → 回 70；人没动 → 降到下一档（70→30→名字本体）
    li = 0
    for rnd in range(max_rounds):
        if m.estop_pressed():
            log("  [换站位] 收到 F9 急停，停手")
            return {"ok": False, "why": "F9 急停"}
        # 起点附近先扫两帧（NPC 常就刷在起点边上，别一动镜头就漏掉）
        c = g.find_npc(h, "_tw_eye%da" % rnd)
        if c and not npc.npc_ok(c, *m.client_size(h)):
            c = None
        if not c:
            time.sleep(1.0)
            c = g.find_npc(h, "_tw_eye%db" % rnd)
            if c and not npc.npc_ok(c, *m.client_size(h)):
                c = None
        if c and npc._blocked(c, *m.client_size(h)):
            c = None
        if not c:
            # 没弹出菜单、人也没动 → 从当前位置接着走剩下的巡逻路径（不回头从第1点重走，
            # 人已经离开录制起点，回头重走会让整条路线平移，走到楼梯口就上三楼）。
            log("  [换站位] 第%d轮：接着走巡逻路径（从第%d点）" % (rnd + 1, max(0, pos) + 1))
            # 新录制 npc_roam9.json（99 点）里同屏连点大多是"同一位置连按"，
            # 人走到那格就停、不会累积前进，所以按原时间轴回放 = 手点节奏，不再额外等停。
            c, pos = npc.roam_simple(h, "npc_roam11.json", start_i=max(0, pos), wait_still=True)
            if not c:
                if pos == -1:
                    log("  [换站位] 巡逻途中已不在二楼，停止（不在这张图上乱走）")
                    return {"ok": False, "why": "不在二楼"}
                log("  [换站位] 巡逻点走完，NPC 整圈没进视野，再走一圈")
                continue
        place = _place_text(h, "_tw_p%d" % rnd)
        log("  [换站位] 第%d轮 楼层=%r 认到 (%d,%d,%d,%d)"
            % (rnd + 1, place, c['x'], c['y'], c['w'], c['h']))
        if _is_3f(place):
            log("  [换站位] 已在三楼，立刻停")
            return {"ok": False, "why": "上到三楼了"}

        cw, ch = m.client_size(h)
        # 点它名字下方 off 像素（或名字本体）那一下 —— 游戏会自己寻路贴近并弹出交易菜单。
        off = (70, 30, 0)[li]
        fx = c['x'] + c['w'] // 2 - 8
        if off:
            fy = c['y'] + c['h'] + off - 31
        else:
            fy = c['y'] + c['h'] // 2 - 31
        if npc.in_ui(fx, fy, cw, ch):
            # 压到界面区时逐级收紧：70 → 35 → 名字本体
            fy = c['y'] + c['h'] + 35 - 31
            if npc.in_ui(fx, fy, cw, ch):
                fy = c['y'] + c['h'] // 2 - 31
                if npc.in_ui(fx, fy, cw, ch):
                    log("  [点NPC] 这一档(%s)压界面区，这轮放过" % ("名字下%d" % off if off else "名字本体"))
                    continue
            log("  [点NPC] 名字下%d压界面区 → 改点 (%d,%d) 先走近" % (off, fx, fy))
        log("  [点NPC] 第%d轮 点%s (%d,%d)" % (rnd + 1, "名字下%d像素" % off if off else "名字本体", fx, fy))
        # 不管人在哪、离多远，一律就点这一下。
        # 用户规则：点完如果发现自己在移动 → 立刻停止巡逻，等它自己走到位，再点第二次。
        m.click_client(h, fx, fy)
        time.sleep(0.3)
        moved = _is_moving(h)
        if moved:
            log("  [点NPC] 点完人在走 → 停止巡逻，等它走到位")
            t0 = time.time()
            while time.time() - t0 < 12.0:
                time.sleep(0.35)
                if m.estop_pressed():
                    log("  [急停] 收到 F9，已停止全部点击")
                    return {"ok": False, "why": "F9 急停"}
                if not _is_moving(h):
                    break
            log("  [点NPC] 已走到位，重新定位 NPC 再点一次（名字下70）")
            c2 = g.find_npc(h, "_tw_again%d" % rnd) or c
            fx2 = c2['x'] + c2['w'] // 2 - 8
            fy2 = c2['y'] + c2['h'] + 70 - 31
            if npc.in_ui(fx2, fy2, cw, ch):
                log("  [点NPC] 第二次脚点 (%d,%d) 压界面区，放弃这轮" % (fx2, fy2))
                continue
            m.click_client(h, fx2, fy2)
            log("  [点NPC] 第二次点击 (%d,%d)" % (fx2, fy2))
        ok = False
        t0 = time.time()
        while time.time() - t0 < 10.0:
            time.sleep(0.4)
            if m.estop_pressed():
                log("  [急停] 收到 F9，已停止全部点击")
                return {"ok": False, "why": "F9 急停"}
            if npc.menu_open(h):
                ok = True
                break
        if ok:
            log("  [点NPC] 弹出菜单（像素判据 ✓）")
            sold = npc.sell_all(h)
            return {"ok": True, "sold_closed": sold, "round": rnd + 1}
        # 没弹菜单：动了 → 说明走近了，回到点名字下70；没动 → 降到下一档（70→30→名字本体）
        if moved:
            li = 0
        else:
            li = min(li + 1, 2)
        log("  [点NPC] 10秒没弹菜单，下一轮点%s，接着巡逻换站位"
            % ("名字下%d像素" % (70, 30, 0)[li] if li < 2 else "名字本体"))
    return {"ok": False, "why": "%d 轮都没弹出菜单" % max_rounds}


def try_sell_once(h):
    """只测一次卖货（按用户讲的走路机制）：
    定位到 NPC → 左键点它名字下方约 70 像素的点位一次（游戏会自动寻路贴近）→ 等 5 秒
    → 弹出菜单就算成功并全队出售；没弹就重新定位它的位置再点一次，最多 3 次。
    失败立即返回，不巡逻第二轮、不回城、不重站。
    """
    c = g.find_npc(h, "_t4_npc")
    if c and (c['x'] < 220 and c['y'] < 140):
        log("  [测试] 认到的是左上角界面文字，忽略")
        c = None
    if c and npc._blocked(c, *m.client_size(h)):
        log("  [测试] 眼前候选贴边被挡，当没认到")
        c = None
    if not c:
        log("  [测试] 眼前没有，跑一遍巡逻宏找")
        c = npc.roam_segments(h, CFG["roam_macro"], CFG["roam_speed"])
    if not c:
        log("  [测试] 没找到 NPC，停")
        return {"ok": False, "why": "没找到 NPC"}
    log("  [测试] 认到 NPC (%d,%d,%d,%d)，停止一切工作" % (c['x'], c['y'], c['w'], c['h']))
    place = _place_text(h, "_t4p0")
    log("  [测试] 点前楼层=%r" % place)
    if _is_3f(place):
        log("  [测试] 已经在三楼，立刻停")
        return {"ok": False, "why": "上到三楼了"}

    fx = c['x'] + c['w'] // 2 - 8
    fy = c['y'] + c['h'] + 70 - 31          # 整窗 +70 像素，转客户区 -31

    # 第 1 次：点一下 → 干等 10 秒看菜单
    # 第 2 步（第 1 次失败才走）：再等 5 秒 → 同一点再点一次 → 再等 10 秒判定
    for att in range(2):
        log("  [测试] 第%d次：左键点名下70像素 (%d,%d)" % (att + 1, fx, fy))
        m.click_client(h, fx, fy)
        txt = ''
        t0 = time.time()
        while time.time() - t0 < 10.0:
            time.sleep(0.5)
            txt = npc.menu_text(h)
            if '全队出售' in txt or '取消' in txt:
                break
        if '全队出售' in txt or '取消' in txt:
            log("  [测试] 菜单弹出：%r" % txt)
            npc.sell_all(h)
            return {"ok": True, "menu": txt}
        if att == 0:
            log("  [测试] 第一次没弹菜单，等 5 秒再点一次")
            time.sleep(5.0)
    log("  [测试] 两次都没弹菜单，停")
    return {"ok": False, "why": "两次点击都没弹出菜单"}


def try_sell_2f_once(h):
    """只测一次：眼前认 NPC → 不行就跑一遍巡逻宏 → 贴靠 → 全队出售。

    失败立即返回，不回城、不重站、不跑第二轮。
    """
    c = g.find_npc(h, "_t2_npc")
    if c and npc._blocked(c, *m.client_size(h)):
        log("  [测试] 眼前候选贴边被挡，当没认到")
        c = None
    if not c:
        log("  [测试] 眼前没有，跑一遍巡逻宏找")
        c = npc.roam_segments(h, CFG["roam_macro"], CFG["roam_speed"])
    if not c:
        log("  [测试] 巡逻完没找到 NPC，停")
        return {"ok": False, "why": "没找到 NPC"}
    log("  [测试] 认到 NPC (%d,%d,%d,%d)" % (c['x'], c['y'], c['w'], c['h']))
    if not npc.approach(h, c):
        log("  [测试] 贴靠或点击失败，停")
        return {"ok": False, "why": "贴靠或点击没弹出菜单"}
    npc.sell_all(h)
    log("  [测试] 全队出售已点")
    return {"ok": True}


def sell_2f(h):
    """找 NPC 卖货：眼前认到就贴靠；贴靠不成不能就此放弃——回旅馆入口重站，
    按录制起点跑巡逻宏（宏是绝对点位，站位不对会走歪），换站位再找。最多 3 轮。"""
    for rnd in range(3):
        c = g.find_npc(h, "_ml_npc")
        if c and npc._blocked(c, *m.client_size(h)):
            log("  眼前候选贴边被按钮栏挡住，换站位")
            c = None
        if not c:
            log("  第%d轮：从入口巡逻找" % (rnd + 1))
            c = npc.roam_segments(h, CFG["roam_macro"], CFG["roam_speed"],
                                  reverse=(rnd % 2 == 1))
        if c and npc.approach(h, c):
            npc.sell_all(h)
            return True
        if c:
            log("  第%d轮贴靠没成" % (rnd + 1))
        else:
            log("  第%d轮巡逻没认到" % (rnd + 1))
        if rnd == 2:
            break
        log("  回旅馆入口重站，再来一轮")
        if not (_hunt_off(h) and enter_inn(h) and upstairs(h)):
            log("  回入口失败，停止卖货")
            return False
    log("  多轮都没贴成魔石贩卖员")
    return False


# ============ 段：回城 -> 练级传送石 -> 回点进洞 ============

TPL_LVL = os.path.join(HERE, "tpls", "lvl_tp.png")
TPL_INN = os.path.join(HERE, "tpls", "inn_icon.png")
TPL_GO = os.path.join(HERE, "tpls", "go_btn.png")
MAP_REGION = (150, 70, 840, 545)
INN_THR = 25.0          # 旅馆模板真命中 avg≈0，无旅馆画面误配 ≥31，留 6 余量
GO_THR = 18.0           # 前往按钮模板真命中 avg≈10


def _load(path):
    return pngio.read_png(path)


def _match_rgb(screen_path, tpl_path, region=MAP_REGION, step=2):
    """16 点粗筛 + ±3 全像素细化的 RGB 模板匹配，返回 {avg,x,y,w,h} 或 None。"""
    W, H, px = _load(screen_path)
    tw, th, tp = _load(tpl_path)
    x0, y0, x1, y1 = region
    x1 = min(x1, W - tw)
    y1 = min(y1, H - th)
    pts = [((i * 17 + 4) % tw, (i * 7 + 2) % th) for i in range(16)]
    best = None
    for y in range(y0, y1 + 1, step):
        for x in range(x0, x1 + 1, step):
            s = 0
            for tx, ty in pts:
                si = ((y + ty) * W + (x + tx)) * 4
                ti = (ty * tw + tx) * 4
                s += (abs(px[si] - tp[ti]) + abs(px[si + 1] - tp[ti + 1])
                      + abs(px[si + 2] - tp[ti + 2]))
            if best is None or s < best[0]:
                best = (s, x, y)
    if best:
        bx, by = best[1], best[2]
        fine = None
        for y in range(max(y0, by - 3), min(y1, by + 3) + 1):
            for x in range(max(x0, bx - 3), min(x1, bx + 3) + 1):
                s = 0
                for ty in range(th):
                    sb = (y + ty) * W * 4
                    tb = ty * tw * 4
                    for tx in range(tw):
                        si = sb + (x + tx) * 4
                        ti = tb + tx * 4
                        s += (abs(px[si] - tp[ti]) + abs(px[si + 1] - tp[ti + 1])
                              + abs(px[si + 2] - tp[ti + 2]))
                if fine is None or s < fine[0]:
                    fine = (s, x, y)
        if fine:
            best = fine
    if not best:
        return None
    s, x, y = best
    return {"avg": s / float(tw * th * 3), "x": x, "y": y, "w": tw, "h": th}


def match_lvl(screen_path, tpl_path=TPL_LVL, region=MAP_REGION, step=2):
    """RGB 模板匹配「练级传送石」蓝菱形标签，返回 {avg,x,y,w,h} 或 None。"""
    return _match_rgb(screen_path, tpl_path, region, step)


def match_inn(screen_path, region=MAP_REGION, step=2):
    """RGB 模板匹配「冒险者旅馆」地标（白房子+金字），avg 低于 INN_THR 才算命中。"""
    r = _match_rgb(screen_path, TPL_INN, region, step)
    if r and r["avg"] <= INN_THR:
        return r
    return None


def match_go(screen_path, region=(150, 80, 840, 300), step=2):
    """RGB 模板匹配气泡里的「前往」按钮，avg 低于 GO_THR 才算命中。"""
    r = _match_rgb(screen_path, TPL_GO, region, step)
    if r and r["avg"] <= GO_THR:
        return r
    return None


def _in_cave(txt):
    """是否在「奇怪的洞窟」。OCR 常把「窟」读成「也/窑/室」，只认「洞」这一字最稳；
    法兰城/芙蕾雅地名都没有「洞」字，不会误判。"""
    if not txt:
        return False
    return ("洞" in txt) or ("窟" in txt)


def _place_text(h, tag):
    """读地名：昨晚那套快读（f.place）。

    回城验收、进旅馆、等到达、上楼这些段落一律用它，跟昨晚完全一致，
    不要在这些流程里改成开图读——那会同时改慢和改坏成功率。
    """
    try:
        return f.place(h, tag)
    except Exception:
        return ""


_PLACE_KEYS = ("洞", "窟", "城", "镇", "村", "旅馆")


def _cave_place(h, tag, tries=3):
    """判「在不在练级点」专用：不点地图，直接读右上角标题条（f.place）。

    只在三处调：开局定位、点遇敌前、长时间没战斗时的复核。
    之所以不用开图读（f.map_place）：那要多点 2 下地图按钮、多花约 6 秒。
    但标题条读法有噪声：实测 8 次里 5 次读到「风之洞窟1」、1 次读空、还会读成坐标数字「10」。
    所以读到「不像地名」就重读，最多 tries 次；仍然不像就返回 ''，调用方当「不知道」。
    读不出返回 ''，调用方必须当成「不知道」，不许当成野外。
    """
    for i in range(tries):
        # 战斗中右上角被「技巧」按钮盖住，读也读不到，别白花 3 次 OCR（约 18 秒）
        if m.ui_layout(h) == "battle":
            return ""
        try:
            txt = f.place(h, "%s_%d" % (tag, i))
        except Exception:
            txt = ""
        if txt and any(k in txt for k in _PLACE_KEYS):
            return txt
        time.sleep(0.3)
    return ""


# 右上角小地图下方那行坐标（窗口坐标）：「241.78」；地名在上面一行。
# 宽 72 是为了容下最长写法（如 159.152 共 7 个字符，约 48 像素，居中排布左右都要留量），
# 太窄会把首位切掉，切出来的数字有可能凑巧等于练级点坐标。
XY_BOX = (850, 157, 72, 20)
# 练级点坐标 25.23（用户确认：这个点原地练、下次来还是这里）。
# OCR 会把小数点读丢（241.78 -> '24178'），所以只比对数字串。
LVL_XY_DIGITS = "2523"


def _read_xy_digits(h, tag="_xy"):
    """读右上角坐标那行，返回 (原文, 纯数字串)。读不出返回 ('','')。

    数字字形简单，OCR 比中文地名稳得多，所以坐标优先、地名兜底。
    实测同一张图：scale=6 只读到 '25'，scale=8 才读全 '2523'；
    所以多档试、取数字最多的那次（命中目标就提前停）。
    """
    m.grab_window_png(h, tag + ".png")
    try:
        f.crop(tag + ".png", tag + "_c.png", *XY_BOX)
    except Exception:
        return "", ""
    best_raw, best = "", ""
    for s in (8, 6, 4):
        try:
            rows = ocrlib.lines(tag + "_c.png", scale=s)
        except Exception:
            continue
        raw = "".join(r["norm"] for r in rows)
        dig = "".join(ch for ch in raw if ch.isdigit())
        if len(dig) > len(best):
            best_raw, best = raw, dig
        if best == LVL_XY_DIGITS:
            break
    return best_raw, best


def _at_lvl_point(h, tag="_lv"):
    """在不在练级点：返回 True / False / **None（不知道）**。

    用户定的规矩：**坐标数字对上了才算在**。所以：
      - 坐标读全且 == 2523        -> True   在
      - 坐标读全且 != 2523        -> False  明确不在（可以去回城）
      - 地名读到「洞/窟」          -> True
      - 地名读到「城/镇/村/旅馆」   -> False
      - 两个都读不到（面板盖着/战斗中/黑帧）-> None  不知道，**调用方不许动作**

    2026-11-20 的教训：原来把"读不出"归进"不在"，于是地图一盖住小地图就判回城，
    每 6 分钟一轮、整夜空转 44 次。
    """
    raw, dig = _read_xy_digits(h, tag + "_xy")
    log("  坐标原文=%r 数字=%r" % (raw, dig))
    if len(dig) >= 3:
        return dig == LVL_XY_DIGITS
    pz = _cave_place(h, tag + "_pz")
    log("  坐标读不全，退地名=%r" % (pz[:14],))
    if pz and ("洞" in pz or "窟" in pz):
        return True
    if pz and (any(k in pz for k in ("城", "镇", "村")) or "旅馆" in pz):
        return False
    return None


# 允许“只露出一部分”的水晶：门槛按局部黄色簇调低（完整时是 40~55 宽 / 45~70 高）
CRYSTAL = {"min_pix": 120, "y_min": 120, "w_min": 30, "h_min": 35, "w_max": 62, "h_max": 78, "white_core": 18}

# 看不到水晶时的扫视步：八方向轮流走一格（实测 40 像素≈1 格；右上=+x，右下=+y）
SCAN_DIRS = [
    (520, 218, "+右上"),
    (520, 298, "+右下"),
    (440, 218, "-左上"),
    (440, 298, "-左下"),
    (480, 203, "+上"),
    (480, 313, "-下"),
    (440, 258, "-左"),
    (520, 258, "+右"),
]


def _ui_rect(x, y, cw, ch):
    """界面禁区的快速矩形版（和 ui_mask.json 那套一致）：识别/走路时这些地方一律不算。"""
    if y < 70:
        return True
    if x < 195 and y < 200:
        return True
    if x < 44 and y < 340:
        return True
    if y > ch - 105:
        return True
    if x > cw - 270 and y < 200:
        return True
    if x < 270 and y > ch - 130:
        return True
    return False




def _find_crystal(h, tag="_cr"):
    """找芙蕾雅洞口那颗黄色水晶，返回客户区坐标；没有返回 None。

    实测：水晶亮黄 r≈250 g≈214 b≈10~90，约 40~55 宽 / 45~70 高，中心带一片白光；
    位置可能在画面中部，不一定在下半部（站在 532,41 时它就在左上 y≈258）。
    洞里的黄土地、草地、玩家金发、右上小地图都会被「纯黄 + 尺寸 + 白核 + 位置」挡掉。
    """
    p = tag + ".png"
    m.grab_window_png(h, p)
    W, H, px = pngio.read_png(p)
    hits = []
    for y in range(CRYSTAL["y_min"], H - 90):
        base = y * W
        for x in range(4, W - 6):
            if x > 828 and y < 280:      # 右上小地图/打卡/回城
                continue
            i = (base + x) * 4
            r, g, b = px[i], px[i + 1], px[i + 2]
            if r >= 228 and g >= 178 and b <= 105 and (r - b) >= 130:
                hits.append((x, y))
    if not hits:
        return None
    cl = []
    for (x, y) in hits:
        for c in cl:
            if abs(c["cx"] - x) <= 32 and abs(c["cy"] - y) <= 40:
                c["xs"].append(x)
                c["ys"].append(y)
                c["cx"] = sum(c["xs"]) / len(c["xs"])
                c["cy"] = sum(c["ys"]) / len(c["ys"])
                break
        else:
            cl.append({"xs": [x], "ys": [y], "cx": x, "cy": y})
    best = None
    for c in cl:
        n = len(c["xs"])
        if n < CRYSTAL["min_pix"]:
            continue
        x0, x1 = min(c["xs"]), max(c["xs"])
        y0, y1 = min(c["ys"]), max(c["ys"])
        w = x1 - x0 + 1
        hh = y1 - y0 + 1
        if not (CRYSTAL["w_min"] <= w <= CRYSTAL["w_max"] and CRYSTAL["h_min"] <= hh <= CRYSTAL["h_max"]):
            continue
        white = 0
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                i = (y * W + x) * 4
                r, g, b = px[i], px[i + 1], px[i + 2]
                if r >= 238 and g >= 232 and b >= 185:
                    white += 1
        if white < CRYSTAL["white_core"]:
            continue
        if best is None or n > best[0]:
            best = (n, int(c["cx"]), int(c["cy"]))
    if not best:
        return None
    g = m._grab(h)
    if not g:
        return None
    offx, offy = g[3], g[4]
    return (best[1] - offx, best[2] - offy)


def _center_rgb(h, tag, x0=380, y0=150, x1=580, y1=300):
    """画面中部一块的平均色（备用：洞内偏黄褐、芙蕾雅偏绿）。"""
    g = m._grab(h)
    if not g:
        return None
    W, H, data, offx, offy = g[0], g[1], g[2], g[3], g[4]
    r = gg = b = n = 0
    for y in range(y0 + offy, min(H, y1 + offy), 3):
        base = y * W
        for x in range(x0 + offx, min(W, x1 + offx), 3):
            i = (base + x) * 4
            b += data[i]; gg += data[i + 1]; r += data[i + 2]; n += 1
    if not n:
        return None
    return (r // n, gg // n, b // n)


def _place_label(h):
    """读右上角那行地名（小地图上方，如「芙蕾雅」「奇怪的洞窟地下1楼」），不打开地图。"""
    out = []
    try:
        for e in m.ocr_shot(h, 3):
            if e["x"] >= 700 and e["y"] <= 75:
                out.append(e["text"])
    except Exception:
        return ""
    return "".join(out)


def _in_cave_label(txt):
    if not txt:
        return False
    t = m._ocr_norm(txt)
    return ("洞" in t) or ("窟" in t)


def _scan_crystal_click(h, tag):
    """点准一下水晶，然后按距离等它自己走进去（不补点、不中途开图）。"""
    for k in range(4):
        c = _find_crystal(h, "%s_%d" % (tag, k))
        if not c:
            return False
        dist = max(abs(c[0] - CHAR_STAND[0]), abs(c[1] - CHAR_STAND[1]))
        wait = 4.0 + (dist / 40.0) * 1.5      # 约 40 像素一格、一格 1.5 秒，再加 4 秒缓冲
        wait = min(20.0, wait)
        log("  水晶 %s，距离 %d 像素 → 点一下，等 %.1f 秒让它自己走" % (c, dist, wait))
        m.click_client(h, c[0], c[1], src="点水晶")
        t0 = time.time()
        last = ""
        while time.time() - t0 < wait:
            time.sleep(1.0)
            if m.ui_layout(h) == "battle":
                log("  走路中进战斗，等打完再继续看")
                m._wait_field(h, timeout=180)
                continue
            last = _place_label(h)
            if _in_cave_label(last):
                log("  进洞了（右上角地名=%r）" % last)
                return True
        log("  等完还没进洞（地名=%r），重新找水晶再点一次" % last)
    return False

import pngio as _pngio

# 水晶残影形状模板（来自 2026_11_19 22:34 那张截图：水晶被树叶挡住，只露一小条）
_TPL_BOX = (582, 255, 623, 314)
_TPL_TH = 0.48
_TPL_MASK = None
_TPL_TW = 0
_TPL_TH2 = 0
_TPL_N = 0


def _loose(r, g, b):
    return r >= 200 and g >= 160 and b <= 135 and (r - b) >= 80 and (g - b) >= 50


def _ui(x, y, W, H):
    return (y < 70 or (x < 195 and y < 200) or (x < 44 and y < 340)
            or y > H - 105 or (x > W - 270 and y < 200) or (x < 270 and y > H - 130))


def _load_template():
    global _TPL_MASK, _TPL_TW, _TPL_TH2, _TPL_N
    if _TPL_MASK is not None:
        return
    W, H, px = _pngio.read_png("_u1.png")
    x0, y0, x1, y1 = _TPL_BOX
    _TPL_TW = x1 - x0 + 1
    _TPL_TH2 = y1 - y0 + 1
    mask = []
    for y in range(y0, y1 + 1):
        row = []
        for x in range(x0, x1 + 1):
            i = (y * W + x) * 4
            row.append(1 if _loose(px[i], px[i + 1], px[i + 2]) else 0)
        mask.append(row)
    _TPL_MASK = mask
    _TPL_N = sum(sum(r) for r in mask)


def _iou(F, fx, fy):
    inter = union = 0
    for ty in range(_TPL_TH2):
        frow = F[fy + ty]
        trow = _TPL_MASK[ty]
        for tx in range(_TPL_TW):
            a = trow[tx]; b = frow[fx + tx]
            if a or b:
                union += 1
                if a and b:
                    inter += 1
    return inter / float(union) if union else 0.0


def find_crystal_shape(h, tag="shp"):
    """按形状找被树叶挡住的水晶残影（只认这一小条），返回客户区坐标或 None。"""
    _load_template()
    g = m._grab(h)
    if not g:
        return None
    W, H, data, offx, offy = g[0], g[1], g[2], g[3], g[4]
    F = []
    for y in range(H):
        base = y * W
        row = []
        for x in range(W):
            i = (base + x) * 4
            row.append(1 if (_loose(data[i + 2], data[i + 1], data[i]) and not _ui(x, y, W, H)) else 0)
        F.append(row)
    S = [[0] * (W + 1) for _ in range(H + 1)]
    for y in range(H):
        srow = S[y + 1]; prow = S[y]; frow = F[y]
        run = 0
        for x in range(W):
            run += frow[x]
            srow[x + 1] = prow[x + 1] + run

    def win(x, y):
        return S[y + _TPL_TH2][x + _TPL_TW] - S[y][x + _TPL_TW] - S[y + _TPL_TH2][x] + S[y][x]

    best = (0.0, 0, 0)
    for y in range(60, H - 95 - _TPL_TH2, 2):
        for x in range(4, W - 6 - _TPL_TW, 2):
            if win(x, y) >= _TPL_N * 0.45:
                s = _iou(F, x, y)
                if s > best[0]:
                    best = (s, x, y)
    if best[0] < _TPL_TH:
        return None
    cx = best[1] + _TPL_TW // 2 - offx
    cy = best[2] + _TPL_TH2 // 2 - offy
    log("  形状匹配：%.2f 分 @ 客户区 (%d,%d)" % (best[0], cx, cy))
    return (cx, cy)


def walk_cave_route(h, loops=4):
    """回放录制的芙蕾雅走位：每步之前撞战斗就等打完再走这一步，每步之后扫一次水晶。"""
    if not os.path.exists(CAVE_ROUTE):
        log("  没有走位录制 %s" % CAVE_ROUTE)
        return False
    log("  找洞口（录制路线回放 %s）" % CAVE_ROUTE)
    for i in range(1, loops + 1):
        log("  第 %d 圈" % i)
        if _scan_crystal_click(h, "_cr_s%d" % i):
            return True
        res = play_macro(h, CAVE_ROUTE, battle_pause=True, ui_filter=True,
                         on_step=lambda e: _scan_crystal_click(h, "_cr_w"))
        if res == "found":
            return True
        if m.ui_layout(h) is None:
            time.sleep(1.5)
    log("  走完 %d 圈还没找到洞口" % loops)
    return False




def walk_to_cave(h, tries=16):
    """从芙蕾雅落点走到洞口：看到黄水晶就点它（游戏会自己寻路贴近并进洞）；
    暂时看不到就按世界坐标轴小步逼近（右上=+x 一格，右下=+y 一格，实测 40 像素=1 格）。
    遇敌只等打完再重来一轮，不会像走位宏那样被带偏。
    """
    log("  找洞口黄水晶")
    for i in range(tries):
        lay = m.ui_layout(h)
        if lay == "battle":
            log("  战斗中，等打完再继续找洞口")
            if not m._wait_field(h, timeout=120):
                log("  战斗超时未回野外")
                return False
            continue
        if lay is None:
            time.sleep(1.0)
            continue
        c = _find_crystal(h, "_cr%d" % i)
        if c:
            # 和找 NPC 一个套路：不点本体，点它下方 70 像素，让游戏自己寻路贴近。
            # 但水晶贴底时 y+70 会压到底部按钮栏（实测压到「制造」，弹出了制造页），
            # 所以按屏幕高度逐级收：70 -> 35 -> 本体，任何一档只要落在按钮区就继续收紧。
            cw, ch = m.client_size(h)
            ty = c[1] + 70
            if ty > ch - 95 or npc.in_ui(c[0], ty, cw, ch):
                ty = c[1] + 35
            if ty > ch - 80 or npc.in_ui(c[0], ty, cw, ch):
                ty = c[1]
            log("  看到黄水晶 %s，点它下方 -> (%d,%d)" % (c, c[0], ty))
            m.click_client(h, c[0], ty)
            time.sleep(2.4)
            txt = _place_text(h, "_crp%d" % i)
            if _in_cave(txt):
                log("  进洞了(地名=%r)" % txt)
                return True
            continue
        mv = SCAN_DIRS[i % len(SCAN_DIRS)]   # 八方向轮流扫一圈，别朝一个方向一直撞墙
        log("  暂时看不到水晶，往%s走一格" % (mv[2],))
        m.click_client(h, mv[0], mv[1])
        time.sleep(1.7)
    log("  找洞口超时（试了 %d 轮）" % tries)
    return False


def _close_map(h):
    """地图开着就点一下关掉，只关这一次，不做别的。"""
    if _map_is_open(h, "_cm"):
        m.click_client(h, *f.MAP_CLOSE)
        time.sleep(1.0)


# ---- 回练级点：开图拖到东北角死角，视野被边界夹死后坐标固定 ----
# 2026-11-20 实测：回城落点每次随机，但拖到边界后每次都是同一屏（逐像素 0.00% 差异）。
LVL_DRAG_STEP = 300      # 每次拖拽的位移（客户区像素）
LVL_DRAG_L = 4           # 往左拖几次（到东边界）
LVL_DRAG_D = 4           # 往下拖几次（到北边界）
LVL_TP_PT = (445, 299)   # 固定视野里「练级传送石」标签（用户手点记录，勿手改）
LVL_GO_PT = (434, 234)   # 固定视野里气泡「前往」按钮（用户手点记录，勿手改）
LVL_WALK = 50.0          # 点完「前往」后等自动寻路（秒）
LVL_STONE_DIGITS = "24178"  # 法兰城练级传送石绝对坐标 241.78（走到位必须读到这个串）


def _map_drag_to_corner(h):
    """把地图拖到东北角死角：撞到边界后视野固定，不管回城落在哪。"""
    cw, ch = m.client_size(h)
    cx, cy = cw // 2, ch // 2
    for _ in range(LVL_DRAG_L):
        f._drag(h, cx, cy, -LVL_DRAG_STEP, 0)
        time.sleep(0.4)
    for _ in range(LVL_DRAG_D):
        f._drag(h, cx, cy, 0, LVL_DRAG_STEP)
        time.sleep(0.4)


def go_level(h, retries=2):
    """回城 -> 开图拖到东北角 -> 点练级传送石 -> 点前往 -> 等寻路 -> tp_click2 -> 观察。

    旧的「回放 tp_go2 六次拖图」会因惯性漂到莎莲娜岛，已废弃。
    退出前一定复原现场：地图关掉（成功、失败、异常都一样）。
    """
    log("回练级点")
    try:
        _close_map(h)
        if not go_home(h):
            return False

        log("  开图 -> 拖到东北角固定视野")
        m.click_client(h, *f.MAP_OPEN)
        time.sleep(2.2)
        _map_drag_to_corner(h)

        log("  点练级传送石 %s" % (LVL_TP_PT,))
        m.click_client(h, *LVL_TP_PT, src="练级传送石")
        time.sleep(1.3)
        log("  点气泡「前往」%s" % (LVL_GO_PT,))
        m.click_client(h, *LVL_GO_PT, src="前往")
        time.sleep(1.2)
        _close_map(h)

        log("  等自动寻路 %.0f 秒" % LVL_WALK)
        time.sleep(LVL_WALK)

        # ===== 到位验收（2026-11-20 加）=====
        # 昨晚就是这里没有验收：地图没关 → 人被面板挡住走不动 → 后面放传送宏全点空，
        # 却照样往下走，最后靠 120 轮兜底判"不在练级点"→ 回城 → 每 6 分钟一轮、整夜空转。
        mo = _map_is_open(h, "_lv_chk")
        raw, dig = _read_xy_digits(h, "_lv_xy")
        log("  到位验收：地图开着=%s 坐标=%r/%r 目标=%s"
            % (mo, raw, dig, LVL_STONE_DIGITS))
        if dig != LVL_STONE_DIGITS:
            log("  没走到练级传送石 → 这次不传送，返回失败（下一轮重来，不补点）")
            return False

        log("  回放传送宏 %s" % CFG["tp_macro"])
        play_macro(h, CFG["tp_macro"], ui_filter=False)
        time.sleep(CFG.get("tp_wait", 12.0))

        t0 = time.time()
        already = False
        while time.time() - t0 < 15.0:
            if m.ui_layout(h) == "battle":
                already = True
                break
            time.sleep(1.0)
        CFG["_auto_armed"] = True
        if already:
            log("  到点后 15 秒自己进战斗 -> 遇敌本来就开着，不点")
        else:
            _set_auto(h, True)
            log("  到点 15 秒没进战斗 -> 点一次遇敌")
        return True
    finally:
        _close_map(h)
        log("  复原：地图已关")

def _bag_space(h):
    """读一次背包空位数（bag_check 自己开包、翻完 5 页、关包）。读不到返回 None。"""
    try:
        b = m.bag_check(h)
        if b.get("ok"):
            return b["space"]
        log("  查背包失败：%s" % (b.get("reason"),))
    except Exception as e:
        log("  查背包出错: %r" % e)
    return None


def sell_cycle(h, base_space=None, retries=3):
    """卖货整段：卖不成就回城重新进旅馆再卖，最多 retries 次，绝不带着满包回练级点。

    判定口径（按用户要求）：
      - 卖之前不查背包：能走到卖货说明包本来就是满的；
      - 卖完查一次背包，**空位比练级那次查包时的空位多**就算成功；
      - 没传 base_space 时（手工触发等）退化成「空位 > 10」。
    """
    log("=== 回城卖魔石 ===")
    for i in range(retries):
        if i:
            log("  === 卖货重试第 %d 次 ===" % i)
        if not _hunt_off(h):
            log("  遇敌没关掉，这一轮不开回城")
            continue
        if not enter_inn(h):
            log("  没进到旅馆，重试")
            continue
        if not upstairs(h):
            log("  没确认到二楼，重试")
            continue
        # 卖之前不查背包：能走到这一步就说明包是满的（满包才回城卖）
        r = try_sell_walk(h)
        if not r.get("ok"):
            log("  卖货没成：%s，回城重来" % r.get("why"))
            continue
        sp = _bag_space(h)          # 卖完查一次：空位比练级那次多就算成功
        need = (base_space if base_space is not None else 10)
        if sp is not None and sp > need:
            log("  卖货确认：卖完空位=%s，练级时空位=%s（变多 %s 格，算成功）"
                % (sp, base_space, sp - need))
            log("  卖完，回练级点")
            try:
                go_level(h)
            except SystemExit:
                raise
            except Exception as e:
                log("  回练级点出错: %r" % e)
            return True
        log("  卖完空位=%s，没比练级时（%s）变多，判失败回城重来" % (sp, base_space))
        continue
    log("  连续 %d 次都没卖成，先回去练级，下个周期再卖" % retries)
    return False


# ============ 主循环 ============

def _next_bag_interval(space):
    """按剩余空位决定下次查包间隔：**前松后紧**。

    2026-11-20 用户定：查包太频繁会打断练级（一次 45~75 秒），但掉落比经验重要，
    所以空位多的时候尽量不查（省时间），快满的时候反而要勤查（别满包空转丢掉落）。
    """
    if space is None:
        return 1200                     # 读不到：20 分钟
    if space >= 30:
        return 1800                     # 30 分钟（查了也没事可做）
    if space >= 15:
        return 1500                     # 25 分钟
    if space >= 6:
        return 720                      # 12 分钟（开始盯紧）
    return 360                          # 6 分钟（快满了，勤查保住掉落）


def hunt_loop(h):
    count = 0
    seen_battle = False
    was_battle = False
    idle = 0
    no_btl = 0
    empty = 0
    last_bag = time.time()
    log("开始循环；每 %d 分钟查一次包。F8 暂停，F9 退出。" % (CFG["bag_interval"] // 60))
    _close_map(h)

    # ===== 开局固定顺序（按用户要求，不判位置，一律按城里处理）=====
    # 直接查背包：空位 <= 3 算满 → 卖货 → 卖完去练级；空位 >= 15 算不满 → 直接去练级。
    log("  开局：不判位置，按城里处理 → 直接查背包（满<=%d，不满>=%d）"
        % (FULL_SPACE, NOT_FULL_SPACE))

    # 开局先查一次背包：空位 <= FULL_SPACE 算满 → 卖货 → 卖完去练级；否则直接去练级
    # 开局同样先关遇敌：判开关的识图读错过，遇敌开着就翻页会读错空位数
    _hunt_off(h)
    _first = m.bag_cycle(h, auto_home=False, rearm=False)
    last_bag = time.time()
    _sp0 = _first.get("space")
    if not _first.get("ok"):
        log("  查包失败(%s)，先按 %d 分钟" % (_first.get("reason"), CFG["bag_interval"] // 60))
        CFG["_bag_next"] = CFG["bag_interval"]
    elif _sp0 is not None and _sp0 <= FULL_SPACE:
        log("  背包满（空位 %s <= %d）→ 卖货，卖完去练级" % (_sp0, FULL_SPACE))
        CFG["_auto_armed"] = False
        sold = False
        try:
            sold = sell_cycle(h, base_space=_sp0)
            if not sold:
                log("  三次都没卖成，先去练级，下个周期再卖")
                go_level(h)
        except SystemExit:
            raise
        except Exception as e:
            log("  卖货段出错: %r，回城回点\n%s" % (e, traceback.format_exc()))
            try:
                go_level(h)
            except Exception:
                pass
        last_bag = time.time()
        CFG["_bag_next"] = _next_bag_interval(32) if sold else 120
        log("  查包计时重置（下次 %.0f 分钟后）" % (CFG["_bag_next"] / 60.0))
    else:
        CFG["_auto_armed"] = False      # 查包会把遇敌关掉，回到循环里由「点遇敌前的判位置」决定开不开
        CFG["_bag_next"] = _next_bag_interval(_sp0)
        log("  背包没满（空位 %s，满的线 %d）→ 去练级（下次查包 %.0f 分钟后）"
            % (_sp0, FULL_SPACE, CFG["_bag_next"] / 60.0))
        # 已经在洞里就别回城了：重启脚本时原来会无条件走 go_level，白跑一趟回城+传送。
        # 判据只用「洞」字：230 次历史地名读取里，洞里的 46 次全都读到「洞」（窟常被读成翻/也/窑），
        # 而城里/旅馆的读取里一次都没出现过「洞」。读不出或读到别的 → 按老规矩回城，不会更差。
        _r = _at_lvl_point(h, "_ml_start")
        if _r is True:
            log("  已经在练级点，不回城，交给循环重新上膛")
        elif _r is False:
            log("  明确不在练级点 → 回城去练级点")
            try:
                go_level(h)
            except SystemExit:
                raise
            except Exception as e:
                log("  去练级点出错: %r" % e)
        else:
            log("  位置不明（面板盖着/战斗中？）→ 不动作，交给循环里再判")
        last_bag = time.time()

    while True:
        tick()
        lay = m.ui_layout(h)

        if lay is None:
            # 抓不到图（窗口被遮挡/最小化/黑帧）：不点屏，歇一下重试
            idle += 1
            time.sleep(1.5)
            continue

        if lay == "battle":
            seen_battle = True
            idle = 0
            no_btl = 0
            was_battle = True
            # 刚进战斗先等入场动画画完，否则右下 UI 还没绘制，环区全黑会被读成「暗」
            if not CFG.get("_btl_settled"):
                time.sleep(1.4)
                CFG["_btl_settled"] = True
            # 自动判定：每场只校一次；一旦连续 3 场读到「亮」，之后彻底不再验证
            if not CFG.get("_auto_verified") and not CFG.get("_btl_fixed"):
                st = m.ensure_battle_auto(h)
                CFG["_btl_fixed"] = True
                if st[0] is True:
                    CFG["_auto_lit"] = CFG.get("_auto_lit", 0) + 1
                    log("  自动已亮(外环%.1f%%)，累计确认 %d/3"
                        % (st[1] or 0, CFG["_auto_lit"]))
                    if CFG["_auto_lit"] >= 3:
                        CFG["_auto_verified"] = True
                        log("  自动连续 3 次确认亮 → 以后不再验证")
                elif st[0] is False:
                    CFG["_auto_lit"] = 0
                    log("  自动两次仍判暗(外环%.1f%%)，先放着" % (st[1] or 0))
            time.sleep(1.6)
            continue

        # 到点查包：战斗一结束、回到野外就先查，不再等下面 3 秒的地名 OCR。
        # （原来排在读地名之后，地名一读空就 continue，十几秒的空档全被跳过，26 分钟都没触发）
        if time.time() - last_bag >= CFG.get("_bag_next", CFG["bag_interval"]):
            log("到点查背包（已挂 %.1f 分钟）" % ((time.time() - last_bag) / 60.0))
            # 先关遇敌再查：遇敌开着时开背包，随时会被拖进战斗，翻页点击全乱、空位数读错。
            # 2026-11-20 实测：5 分钟里空位从 26 变成 46，明显有一次读错。
            if not _hunt_off(h):
                log("  遇敌没关掉，这次不查包，过 2 分钟再试")
                last_bag = time.time()
                CFG["_bag_next"] = 120
                continue
            CFG["_auto_armed"] = False      # 查完由循环重新上膛点遇敌（避免和 rearm 双重拨开关）
            res = m.bag_cycle(h, auto_home=False, rearm=False)
            last_bag = time.time()
            CFG["_bag_next"] = _next_bag_interval(res.get("space"))
            log("  下次查包间隔 %.0f 分钟（空位 %s）"
                % (CFG["_bag_next"] / 60.0, res.get("space")))
            if not res.get("ok"):
                log("  查包失败：%s" % res)
                _set_auto(h, True)
                CFG["_auto_armed"] = True
            elif res.get("space") is not None and res.get("space") <= FULL_SPACE_LOOP:
                log("  背包满（空位 %s <= %d），走卖货流程" % (res.get("space"), FULL_SPACE_LOOP))
                CFG["_auto_armed"] = False      # 卖完回洞后再点一次
                sold = False
                try:
                    sold = sell_cycle(h, base_space=res.get("space"))
                    if not sold:
                        log("  三次都没卖成，先回点练级，下个周期再卖")
                        go_level(h)
                except SystemExit:
                    raise
                except Exception as e:
                    log("  卖货段出错: %r，回城回点\n%s" % (e, traceback.format_exc()))
                    try:
                        go_level(h)
                    except Exception:
                        pass
                # 卖货+回城+上楼+传送+进洞这一整套要 5 分钟以上。last_bag 只在查包时刷新，
                # 不重置的话回到洞里计时早就超阈值，会一进洞就白查一次包。
                # 卖成了就按「刚卖完≈满空位」重定间隔；没卖成仍按 2 分钟，好尽早再试。
                last_bag = time.time()
                CFG["_bag_next"] = _next_bag_interval(32) if sold else 120
                log("  已回到练级点，查包计时重置（下次 %.0f 分钟后）" % (CFG["_bag_next"] / 60.0))
                count = 0
            else:
                log("  背包未满（空位 %s），继续练" % res.get("space"))
            continue

        if was_battle:
            was_battle = False
            CFG["_btl_settled"] = False
            CFG["_btl_fixed"] = False

        if seen_battle:
            seen_battle = False
            count += 1
            log("战斗结束（累计 %d 场）" % count)

        # 野外：地名只有一个来源（开图读左上角标签），一次约 4~7 秒，绝对不能每轮都读。
        # 每轮只记「多久没打」，连续 no_btl 轮（约 4~5 分钟）没进战斗，才开图确认一次自己在哪：
        # 正常在洞里打怪十几秒就打一场，不会触发；出现只说明人可能被传回城了/卡住了。
        no_btl += 1
        if no_btl >= 120:
            no_btl = 0
            _r = _at_lvl_point(h, "_ml_field")
            if _r is False:
                log("  120 轮没进战斗，且明确不在练级点 → 回城回练级点")
                try:
                    go_level(h)
                except SystemExit:
                    raise
                except Exception as e:
                    log("  回点出错: %r" % e)
                idle = 0
                continue
            if _r is True:
                log("  120 轮没进战斗，但确认还在练级点 → 继续")
            else:
                log("  120 轮没进战斗，位置不明 → 不动作")
        empty = 0
        # 遇敌只在进入挂机时点一次。反复点会把开关来回拨（点了就一直遇敌），
        # 所以这里只做一次性上膛，不再每轮检查、不再补点。
        # 上膛前先观察 15 秒：这段时间要是自己就进战斗，说明遇敌本来就开着，一个都别点。
        if not CFG.get("_auto_armed"):
            log("  进野外，先观察 15 秒确认遇敌是不是已经开着")
            t0 = time.time()
            already = False
            while time.time() - t0 < 15.0:
                if m.ui_layout(h) == "battle":
                    already = True
                    break
                time.sleep(1.0)
            if already:
                CFG["_auto_armed"] = True
                log("  15 秒内自己进战斗 → 遇敌本来就开着，不点")
            else:
                # 点遇敌前先确认在不在练级点：坐标优先（25.23 数字最稳），读不出才退地名
                _r = _at_lvl_point(h, "_ml_arm")
                if _r is True:
                    r = _set_auto(h, True)
                    if r.get("ok"):
                        CFG["_auto_armed"] = True
                        log("  15 秒没进战斗 → 点一次遇敌")
                    else:
                        # 点失败就别标记成已上膛，否则会静默空转、再也不会重点
                        log("  点遇敌没成功，下一轮再试")
                elif _r is False:
                    log("  不在练级点 → 回城回练级点")
                    try:
                        go_level(h)
                    except SystemExit:
                        raise
                    except Exception as e:
                        log("  回点出错: %r" % e)
                else:
                    # 位置不明（地图/背包/NPC 面板盖着，或刚进战斗）：
                    # 一个键都不点，下一轮重判。绝不因为“读不出”就当“不在练级点”去回城。
                    log("  位置不明 → 这次不点遇敌，下一轮再判")

        if idle > 25:
            log("  长时间找不到遇敌按钮，尝试回练级点")
            go_level(h)
            idle = 0
        time.sleep(1.2)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    log("模式: %s" % mode)

    hwnd, title = m.find_game_window()
    if not hwnd:
        log("没找到游戏窗口「%s」，先启动游戏。" % m.DEFAULT_TITLE)
        return 2
    m.user32.SetForegroundWindow(m.wt.HWND(hwnd))
    time.sleep(0.3)
    log("窗口: %s" % title)

    if mode == "map":
        go_home(hwnd)
        enter_inn(hwnd)
        upstairs(hwnd)
    elif mode == "sell2f":
        sell_2f(hwnd)
        go_home(hwnd)
    elif mode == "level":
        go_level(hwnd)
    else:
        hunt_loop(hwnd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
