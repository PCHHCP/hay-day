#!/usr/bin/env python3
"""HayDay 抢购自动化 — 持续扫描模式 (adb 点击)

工作流程:
  1) 用户手动点开邮箱 (脚本不管这一步)
  2) 脚本轮询截图, 按状态扫对应的 6 张模板:
     - newspaper 状态 → 扫 6 张报纸广告卡
     - shelf     状态 → 扫 6 张货架商品 (可连续买多个)
  3) 命中 → 经 adb 点击 → 冷却 100ms → 继续
     - newspaper 命中 → 立即翻到 shelf (点广告进货架)
     - shelf     命中 → 保持 shelf 状态, 继续扫剩余商品
  4) 进入 shelf 后固定 5s 自动回退到 newspaper (一轮购买窗口)
  5) 用户手动关闭货架, 等下一期打开邮箱 → 回到 2

前置条件:
  1) BlueStacks 设置 → 高级 → 打开 Android 调试桥 (默认端口 5555)
  2) brew install android-platform-tools

用法:
  python3 autobuy.py                  持续扫描 (默认), Ctrl+C 退出
  python3 autobuy.py --adb-port 5555  自定义 ADB 端口
  python3 autobuy.py --cooldown 200   自定义命中冷却毫秒数
  python3 autobuy.py --interval 50    自定义未命中轮询毫秒数
"""

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))

from src import input as adb  # noqa: E402
from src.vision import match_template  # noqa: E402
from src.window import capture, find_bluestacks  # noqa: E402


ROOT = Path(__file__).parent
TEMPLATES_DIR = ROOT / "templates"


# 两组模板, 只有 templates/<name>.png 存在时才会实际加入扫描.
# 报纸页 (邮箱打开后的广告卡) vs 货架页 (点进广告后的商品货架).
# 二者循环交替 — 报纸命中点一次进货架, 货架命中点一次完成购买, 回到报纸.
# 每帧只扫当前状态对应的 6 张, 识别压力减半且避免互相误判.
NEWSPAPER_TOOLS = ("nail", "bolt", "screw", "panel", "plank", "tape")
SHELF_TOOLS = tuple(f"{n}_shelf" for n in NEWSPAPER_TOOLS)

STATE_NEWSPAPER = "newspaper"
STATE_SHELF = "shelf"

# 货架状态驻留时长: 从进入 shelf 开始计时, 期间连续扫剩余商品支持多件购买.
# 超时固定回到 newspaper 等下一期报纸, 避免卡死在空货架上反复扫.
SHELF_TIMEOUT_S = 5.0

# 报纸广告卡和货架商品基本是固定 UI overlay, 留适度多尺度兼容窗口缩放
# 顺序: 先试最可能命中的 (中间段), 配合 match_template 的短路加速
TOOL_SCALES = (0.80, 0.70, 0.90, 0.60, 1.00, 0.50, 1.10)
TOOL_THRESHOLD = 0.82

DEFAULT_COOLDOWN_MS = 100
DEFAULT_POLL_INTERVAL_MS = 50

# 匹配前把截图和模板都缩小到 1/MATCH_DOWNSCALE, 像素量少 N^2, matchTemplate 快 ~N^2.
# 命中坐标乘回去还原, tap 精度不变.
# 配合更严的阈值 (0.82) 防止降采样后 plank/麦穗一类的擦边误判.
MATCH_DOWNSCALE = 2


def _log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


def _load_templates(names):
    """启动时把模板一次性缩小, 跟每帧缩小后的截图同比例."""
    loaded, missing = [], []
    for name in names:
        path = TEMPLATES_DIR / f"{name}.png"
        tpl = cv2.imread(str(path))
        if tpl is None:
            missing.append(name)
            continue
        if MATCH_DOWNSCALE != 1:
            h, w = tpl.shape[:2]
            tpl = cv2.resize(
                tpl,
                (w // MATCH_DOWNSCALE, h // MATCH_DOWNSCALE),
                interpolation=cv2.INTER_AREA,
            )
        loaded.append((name, tpl))
    if missing:
        _log("WARN", f"模板缺失, 跳过: {', '.join(missing)}")
    return loaded


def _scale_hit_up(hit, factor):
    """把 detect 返回的 half-space 坐标/尺寸放大回原图坐标系."""
    if hit is None or factor == 1:
        return hit
    x, y, w, h = hit["box"]
    out = dict(hit)
    out["x"] = hit["x"] * factor
    out["y"] = hit["y"] * factor
    out["box"] = (x * factor, y * factor, w * factor, h * factor)
    return out


def detect_best_tool(image, templates):
    """对每个 template 跑多尺度匹配, 第一个过阈值的直接返回 (短路)."""
    for name, tpl in templates:
        r = match_template(image, tpl, threshold=TOOL_THRESHOLD, scales=TOOL_SCALES)
        if r is not None:
            r["name"] = name
            return r
    return None


def scan_loop(cooldown_ms, poll_interval_ms, adb_port):
    newspaper_templates = _load_templates(NEWSPAPER_TOOLS)
    shelf_templates = _load_templates(SHELF_TOOLS)
    if not newspaper_templates or not shelf_templates:
        _log("ERR", "报纸或货架模板缺失, 先在 templates/ 下放好 .png")
        return 1

    try:
        target, (aw, ah) = adb.init(port=adb_port)
    except RuntimeError as e:
        _log("ERR", f"adb 初始化失败: {e}")
        return 1

    cooldown_s = cooldown_ms / 1000.0
    poll_s = poll_interval_ms / 1000.0

    print("=" * 56)
    print(" HayDay 抢购 — 持续扫描模式 (adb)")
    print("=" * 56)
    print(f"  报纸模板: {', '.join(n for n, _ in newspaper_templates)}")
    print(f"  货架模板: {', '.join(n for n, _ in shelf_templates)}")
    print(f"  命中冷却: {cooldown_ms}ms   未命中轮询: {poll_interval_ms}ms")
    print(f"  货架超时回退: {SHELF_TIMEOUT_S}s")
    print(f"  ADB     : {target}  Android 屏幕 {aw}x{ah}")
    print()
    print(" 流程: 你打开邮箱 → 脚本识别广告 → 点 → 识别货架商品 → 点购买")
    print("       你关闭货架 → 等下期报纸再打开邮箱")
    print()
    print(" Ctrl+C 退出")
    print("=" * 56, flush=True)

    win = find_bluestacks()
    if win is None:
        _log("ERR", "未找到 BlueStacks 窗口, 确认已开且可见.")
        return 1
    _log("OK", f"BlueStacks {win['w']}x{win['h']} @ ({win['x']},{win['y']})")

    hits = 0
    frames = 0
    last_status = time.time()
    state = STATE_NEWSPAPER
    shelf_entered_at = 0.0  # 进入 shelf 状态的时间, 用于超时回退

    try:
        while True:
            frames += 1
            # 每 30 帧刷新一次窗口位置, 支持用户拖动 BlueStacks
            # (每帧都查 Quartz 全屏窗口列表太贵)
            if frames % 30 == 0:
                win = find_bluestacks() or win

            # 货架状态固定驻留 SHELF_TIMEOUT_S, 到点就回报纸 (不论是否命中过).
            # 货架支持多件购买, 所以这里不按"未命中"而是按"已进货架多久"判定.
            if state == STATE_SHELF and (time.time() - shelf_entered_at) > SHELF_TIMEOUT_S:
                _log("STATE", f"shelf 驻留 {SHELF_TIMEOUT_S}s 到期, 回到 newspaper")
                state = STATE_NEWSPAPER

            templates = newspaper_templates if state == STATE_NEWSPAPER else shelf_templates

            t0 = time.perf_counter()
            img = capture(win)
            t_cap = time.perf_counter()
            iw, ih = img.shape[1], img.shape[0]

            if MATCH_DOWNSCALE != 1:
                small = cv2.resize(
                    img,
                    (iw // MATCH_DOWNSCALE, ih // MATCH_DOWNSCALE),
                    interpolation=cv2.INTER_AREA,
                )
            else:
                small = img
            hit = detect_best_tool(small, templates)
            hit = _scale_hit_up(hit, MATCH_DOWNSCALE)
            t_det = time.perf_counter()

            cap_ms = (t_cap - t0) * 1000
            det_ms = (t_det - t_cap) * 1000

            if hit is not None:
                hits += 1
                t_tap0 = time.perf_counter()
                ax, ay = adb.tap(hit["x"], hit["y"], (iw, ih))
                tap_ms = (time.perf_counter() - t_tap0) * 1000
                _log(
                    "TAP",
                    f"[{state}] {hit['name']} score={hit['score']:.3f} scale={hit['scale']:.2f} "
                    f"img=({hit['x']},{hit['y']}) android=({ax},{ay}) "
                    f"cap={cap_ms:.0f}ms det={det_ms:.0f}ms tap={tap_ms:.0f}ms",
                )

                # newspaper 命中 → 进货架并开始 5s 倒计时.
                # shelf 命中 → 保持 shelf, 继续扫剩余商品; 回报纸只靠超时.
                if state == STATE_NEWSPAPER:
                    state = STATE_SHELF
                    shelf_entered_at = time.time()

                time.sleep(cooldown_s)
                continue

            now = time.time()
            if now - last_status > 5.0:
                _log("..", f"[{state}] 待命中 ({frames} 帧, {hits} 次命中)")
                last_status = now

            time.sleep(poll_s)
    except KeyboardInterrupt:
        print()
        _log("BYE", f"退出. 总计 {frames} 帧, {hits} 次命中.")
        return 0


def main():
    p = argparse.ArgumentParser(description="HayDay 抢购自动化 (adb 点击)")
    p.add_argument(
        "--cooldown",
        type=int,
        default=DEFAULT_COOLDOWN_MS,
        help=f"命中后冷却毫秒数 (默认 {DEFAULT_COOLDOWN_MS})",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL_MS,
        help=f"未命中轮询毫秒数 (默认 {DEFAULT_POLL_INTERVAL_MS})",
    )
    p.add_argument(
        "--adb-port",
        type=int,
        default=5565,
        help="BlueStacks ADB 端口 (默认 5555)",
    )
    args = p.parse_args()

    sys.exit(
        scan_loop(
            cooldown_ms=args.cooldown,
            poll_interval_ms=args.interval,
            adb_port=args.adb_port,
        )
    )


if __name__ == "__main__":
    main()
