"""BlueStacks 窗口定位与截图"""

import sys

import cv2
import mss
import numpy as np

try:
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListOptionOnScreenOnly,
    )
except ImportError:
    print("错误: 需要 pyobjc-framework-Quartz", file=sys.stderr)
    print("运行: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


def find_bluestacks():
    """返回最大的 BlueStacks 窗口信息 dict 或 None。"""
    windows = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID
    )
    candidates = []
    for w in windows:
        owner = w.get("kCGWindowOwnerName", "") or ""
        if "BlueStacks" not in owner:
            continue
        bounds = w.get("kCGWindowBounds", {})
        width = int(bounds.get("Width", 0))
        height = int(bounds.get("Height", 0))
        if width < 400 or height < 400:
            continue
        candidates.append(
            {
                "x": int(bounds.get("X", 0)),
                "y": int(bounds.get("Y", 0)),
                "w": width,
                "h": height,
                "pid": w.get("kCGWindowOwnerPID"),
                "window_id": w.get("kCGWindowNumber"),
                "owner": owner,
                "title": w.get("kCGWindowName", "") or "",
            }
        )
    if not candidates:
        return None
    candidates.sort(key=lambda c: c["w"] * c["h"], reverse=True)
    return candidates[0]


_SCT = None


def capture(window):
    """按窗口位置截图，返回 BGR ndarray。

    mss 实例常驻复用, 避免每帧 __enter__/__exit__ 重建 CoreGraphics 会话.
    """
    global _SCT
    if _SCT is None:
        _SCT = mss.mss()
    monitor = {
        "left": window["x"],
        "top": window["y"],
        "width": window["w"],
        "height": window["h"],
    }
    raw = np.array(_SCT.grab(monitor))
    return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
