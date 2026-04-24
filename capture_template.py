#!/usr/bin/env python3
"""
HayDay Template Capture Tool
============================

捕获 BlueStacks 窗口截图并辅助裁剪模板，用于后续图像识别。

用法:
  python3 capture_template.py info
      显示检测到的 BlueStacks 窗口信息（位置、大小、Retina 缩放）

  python3 capture_template.py snapshot [NAME]
      截取 BlueStacks 当前窗口，保存到 snapshots/<NAME>.png
      不给 NAME 则用时间戳命名

  python3 capture_template.py crop SNAPSHOT
      打开指定快照，交互式框选并保存为模板到 templates/
      可反复框选，每次输入模板名

  python3 capture_template.py test TEMPLATE [SNAPSHOT]
      测试模板在快照中的匹配效果。不给 SNAPSHOT 则用实时截图
      输出：最佳匹配位置、中心点、置信度、可视化图

  python3 capture_template.py list
      列出当前所有快照和模板

使用流程:
  1. 在 BlueStacks 打开 HayDay，调到要捕获的画面
  2. python3 capture_template.py snapshot mainscreen        # 主界面
  3. 在游戏里点开邮箱，看到报纸
  4. python3 capture_template.py snapshot newspaper_page1   # 报纸页
  5. python3 capture_template.py crop snapshots/newspaper_page1.png
  6. 交互式裁出 bolt/nail/panel/tape/plank/screw 六个模板
  7. python3 capture_template.py test bolt newspaper_page1  # 回验证
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))

from src.window import capture, find_bluestacks  # noqa: E402


PROJECT_ROOT = Path(__file__).parent.resolve()
SNAPSHOTS_DIR = PROJECT_ROOT / "snapshots"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
SNAPSHOTS_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)


def capture_bluestacks():
    """截取 BlueStacks 窗口, 返回 (BGR ndarray, window_info)."""
    win = find_bluestacks()
    if win is None:
        print(
            "错误: 未找到 BlueStacks 窗口. 确认 BlueStacks 已打开且窗口可见.",
            file=sys.stderr,
        )
        sys.exit(1)
    return capture(win), win


def resolve_path(user_path: str, default_dir: Path) -> Path:
    """将用户输入的路径解析为真实文件路径。
    优先相对 CWD，其次相对 default_dir。
    """
    p = Path(user_path)
    if p.is_absolute() and p.exists():
        return p
    if p.exists():
        return p.resolve()
    alt = default_dir / p.name
    if alt.exists():
        return alt
    alt_with_ext = default_dir / f"{p.stem}.png"
    if alt_with_ext.exists():
        return alt_with_ext
    return p  # 不存在也返回，调用方负责报错


def unique_path(base_dir: Path, stem: str) -> Path:
    """返回一个不与已有文件冲突的 PNG 路径。
    同名时自动追加 -2, -3, -4 ... 后缀。
    """
    p = base_dir / f"{stem}.png"
    if not p.exists():
        return p
    i = 2
    while True:
        p = base_dir / f"{stem}-{i}.png"
        if not p.exists():
            return p
        i += 1


def fit_to_screen(img, max_dim=1200):
    """把图像缩到 max_dim 以内便于屏幕显示。返回 (display_img, scale)"""
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= max_dim:
        return img, 1.0
    scale = max_dim / longest
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA), scale


# ---------- commands ----------


def cmd_info():
    win = find_bluestacks()
    if win is None:
        print("未找到 BlueStacks 窗口")
        sys.exit(1)
    print("=" * 56)
    print("BlueStacks 窗口信息")
    print("=" * 56)
    print(f"进程      : {win['owner']} (PID {win['pid']})")
    print(f"窗口 ID   : {win['window_id']}")
    print(f"标题      : {win['title']!r}")
    print(f"屏幕位置  : x={win['x']}, y={win['y']}")
    print(f"窗口大小  : {win['w']} × {win['h']} (逻辑点)")

    img, _ = capture_bluestacks()
    h, w = img.shape[:2]
    print(f"截图像素  : {w} × {h}")
    scale = w / win["w"]
    if abs(scale - 1.0) > 0.05:
        print(f"Retina 缩放: × {scale:.2f}  (像素/逻辑点)")
    else:
        print("Retina 缩放: 1.0（非 Retina 或已调整）")
    print()
    print("✓ 窗口正常，可以开始截图")


def cmd_snapshot(name, force=False):
    img, win = capture_bluestacks()
    if name is None:
        name = datetime.now().strftime("snap_%Y%m%d_%H%M%S")
    # 去除用户可能输入的扩展名
    name = Path(name).stem

    if force:
        out = SNAPSHOTS_DIR / f"{name}.png"
    else:
        out = unique_path(SNAPSHOTS_DIR, name)
        if out.name != f"{name}.png":
            print(f"⚠ {name}.png 已存在，自动另存为 {out.name}（想覆盖请加 --force）")

    cv2.imwrite(str(out), img)
    h, w = img.shape[:2]
    print(f"✓ 快照已保存: {out}")
    print(f"  像素尺寸  : {w} × {h}")
    print(f"  窗口位置  : ({win['x']}, {win['y']})")


def cmd_crop(snapshot_path):
    snap = resolve_path(snapshot_path, SNAPSHOTS_DIR)
    if not snap.exists():
        print(f"错误: 找不到快照 {snap}", file=sys.stderr)
        sys.exit(1)

    img = cv2.imread(str(snap))
    if img is None:
        print(f"错误: 无法读取 {snap}", file=sys.stderr)
        sys.exit(1)

    display_img, scale = fit_to_screen(img, max_dim=1200)
    ih, iw = img.shape[:2]

    print(f"快照      : {snap}")
    print(f"像素尺寸  : {iw} × {ih}")
    if scale != 1.0:
        print(f"显示缩放  : × {scale:.2f}（仅显示用，保存的是原始像素）")
    print()
    print("[操作说明]")
    print("  1) 在弹窗里按住鼠标左键拖动框选一个区域")
    print("  2) 按 ENTER / SPACE 确认框选")
    print("  3) 按 C 清除当前框")
    print("  4) 框选成功后回终端输入模板名（回车跳过，q 退出）")
    print()

    while True:
        roi = cv2.selectROI(
            "select template (ENTER=ok, C=clear)",
            display_img,
            showCrosshair=True,
            fromCenter=False,
        )
        cv2.destroyAllWindows()

        if roi == (0, 0, 0, 0):
            print("未框选，结束。")
            break

        x, y, w, h = roi
        if scale != 1.0:
            x = int(round(x / scale))
            y = int(round(y / scale))
            w = int(round(w / scale))
            h = int(round(h / scale))

        x = max(0, min(x, iw - 1))
        y = max(0, min(y, ih - 1))
        w = max(1, min(w, iw - x))
        h = max(1, min(h, ih - y))

        crop = img[y : y + h, x : x + w]
        ch, cw = crop.shape[:2]
        print(f"框选      : 左上=({x}, {y}) 大小={cw}×{ch}")

        preview = crop
        if max(cw, ch) < 200:
            f = 200 / max(cw, ch)
            preview = cv2.resize(
                crop, None, fx=f, fy=f, interpolation=cv2.INTER_NEAREST
            )
        cv2.imshow("preview", preview)
        cv2.waitKey(1)  # 非阻塞：刷新一下显示，焦点还在终端

        name = input("模板名 [空=跳过, q=退出]: ").strip()
        cv2.destroyAllWindows()
        if name.lower() == "q":
            break
        if not name:
            print("已跳过。\n")
            continue
        name = Path(name).stem  # 清掉可能的扩展名
        out_path = TEMPLATES_DIR / f"{name}.png"

        if out_path.exists():
            ans = input(f"{out_path.name} 已存在，覆盖? [y/N]: ").strip().lower()
            if ans != "y":
                print("已跳过。\n")
                continue

        cv2.imwrite(str(out_path), crop)
        print(f"✓ 模板已保存: {out_path}\n")


def cmd_test(template_path, snapshot_path, show=True):
    tpl = resolve_path(template_path, TEMPLATES_DIR)
    if not tpl.exists():
        print(f"错误: 找不到模板 {tpl}", file=sys.stderr)
        sys.exit(1)
    template = cv2.imread(str(tpl))
    if template is None:
        print(f"错误: 无法读取模板 {tpl}", file=sys.stderr)
        sys.exit(1)

    if snapshot_path is None:
        print("未指定快照，使用实时截图...")
        img, _ = capture_bluestacks()
        snap_label = "<实时截图>"
    else:
        snap = resolve_path(snapshot_path, SNAPSHOTS_DIR)
        if not snap.exists():
            print(f"错误: 找不到快照 {snap}", file=sys.stderr)
            sys.exit(1)
        img = cv2.imread(str(snap))
        if img is None:
            print(f"错误: 无法读取 {snap}", file=sys.stderr)
            sys.exit(1)
        snap_label = str(snap)

    th, tw = template.shape[:2]
    ih, iw = img.shape[:2]
    print(f"模板      : {tpl.name}  {tw}×{th}")
    print(f"快照      : {snap_label}  {iw}×{ih}")

    if th > ih or tw > iw:
        print("错误: 模板比快照大，无法匹配", file=sys.stderr)
        sys.exit(1)

    result = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    top_left = max_loc
    bottom_right = (top_left[0] + tw, top_left[1] + th)
    center = (top_left[0] + tw // 2, top_left[1] + th // 2)

    print()
    print(f"最佳位置  : 左上={top_left}  右下={bottom_right}")
    print(f"中心点    : {center}")
    print(f"置信度    : {max_val:.4f}  (NCC)")
    if max_val >= 0.85:
        verdict = "✓ 置信度高，可靠"
    elif max_val >= 0.65:
        verdict = "⚠ 置信度中等，建议优化模板"
    else:
        verdict = "✗ 置信度低，不可靠"
    print(f"结论      : {verdict}")

    vis = img.copy()
    color = (0, 255, 0) if max_val >= 0.65 else (0, 128, 255)
    cv2.rectangle(vis, top_left, bottom_right, color, 3)
    cv2.circle(vis, center, 6, (0, 0, 255), -1)
    label = f"{tpl.stem} {max_val:.3f}"
    cv2.putText(
        vis,
        label,
        (top_left[0], max(top_left[1] - 10, 20)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        color,
        2,
    )

    vis_path = SNAPSHOTS_DIR / f"_match_{tpl.stem}.png"
    cv2.imwrite(str(vis_path), vis)
    print(f"可视化    : {vis_path}")

    if show:
        display, _ = fit_to_screen(vis, max_dim=1200)
        cv2.imshow(f"match: {tpl.stem} (any key to close)", display)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


def cmd_list():
    def _list_dir(title, directory: Path):
        print("=" * 56)
        print(f"{title}  ({directory})")
        print("=" * 56)
        files = sorted(directory.glob("*.png"))
        if not files:
            print("  (空)")
            return
        for p in files:
            img = cv2.imread(str(p))
            size = f"{img.shape[1]}×{img.shape[0]}" if img is not None else "?"
            print(f"  {p.name:42s}  {size}")

    _list_dir("快照 snapshots/", SNAPSHOTS_DIR)
    print()
    _list_dir("模板 templates/", TEMPLATES_DIR)


def main():
    parser = argparse.ArgumentParser(
        description="HayDay 模板捕获工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="详细使用示例见文件顶部 docstring。",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("info", help="显示 BlueStacks 窗口信息")

    p_snap = sub.add_parser("snapshot", help="截取 BlueStacks 窗口")
    p_snap.add_argument("name", nargs="?", default=None)
    p_snap.add_argument(
        "--force", action="store_true", help="同名时直接覆盖（默认会自动追加 -2/-3 后缀）"
    )

    p_crop = sub.add_parser("crop", help="从快照裁剪模板")
    p_crop.add_argument("snapshot")

    p_test = sub.add_parser("test", help="测试模板匹配")
    p_test.add_argument("template")
    p_test.add_argument("snapshot", nargs="?", default=None)
    p_test.add_argument(
        "--no-show", action="store_true", help="不弹出可视化窗口（只保存到磁盘）"
    )

    sub.add_parser("list", help="列出快照和模板")

    args = parser.parse_args()
    if args.cmd == "info":
        cmd_info()
    elif args.cmd == "snapshot":
        cmd_snapshot(args.name, force=args.force)
    elif args.cmd == "crop":
        cmd_crop(args.snapshot)
    elif args.cmd == "test":
        cmd_test(args.template, args.snapshot, show=not args.no_show)
    elif args.cmd == "list":
        cmd_list()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
