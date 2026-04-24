#!/usr/bin/env python3
"""HayDay 棕色空地识别 — 实验脚本 (wheat v1)

只识别, 不操作. 用 HSV 颜色分割 + 形态学清理 + 轮廓形状过滤 (面积 + 填充率)
选出棕色耕地, 再用 approxPolyDP 拟合成紧贴真实边界的多边形 (等距视角下多为
4-6 边形), 并把可视化保存到 wheat/snapshots/.

用法:
  python3 -m wheat.detect <snapshot_path>                              从已存 PNG 读 (默认棕色)
  python3 -m wheat.detect --live                                       实时截 BlueStacks
  python3 -m wheat.detect <path> --color brown                         显式棕色 (空地)
  python3 -m wheat.detect <path> --color gold                          金色 (成熟麦田)
  python3 -m wheat.detect <path> --hsv-lower 8,150,130 --hsv-upper 15,255,210
                                                                       自定义 HSV 阈值 (优先级高于 --color)
  python3 -m wheat.detect <path> --min-area 1000 --min-extent 0.35 --poly-eps 0.01

输出:
  - stdout:
      center=(cx,cy)  bbox=(x,y,w,h)  area=N  image_size=(W,H)
      polygon (K corners): [(x0,y0), ...]
  - 文件: wheat/snapshots/<basename>_detected.png
          或 wheat/snapshots/live_YYYYMMDD_HHMMSS_detected.png

未找到棕色区域时打印 `no brown region found` 并以非零码退出.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# 跟 autobuy/main.py 保持一致, 允许作为 `python3 -m wheat.detect` 调用时解析 src.*
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.window import capture, find_bluestacks  # noqa: E402


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SNAPSHOTS_DIR = PROJECT_ROOT / "wheat" / "snapshots"

# 颜色预设: HSV 阈值按真实截图像素采样 + 留 buffer 确定.
# brown: 棕色空地 (未种的耕地). 像素簇 H≈10-12, S≈200-210, V≈160-190.
# gold:  金色成熟麦田. 像素簇 H≈22-28, S≈183-255, V≈196-255 (阴影边缘 V 最低 196).
# 形态学/面积/extent/poly_eps 所有颜色共用 (实测两种场景都不需要差异化调整).
COLOR_PRESETS: dict[str, dict[str, tuple[int, int, int]]] = {
    "brown": {
        "hsv_lower": (8, 150, 130),
        "hsv_upper": (15, 255, 210),
    },
    "gold": {
        "hsv_lower": (18, 150, 180),
        "hsv_upper": (32, 255, 255),
    },
}
DEFAULT_COLOR = "brown"

# 形态学: 椭圆核比矩形核更接近"圆盘"结构元, 不易沿轴产生毛刺.
# open 3x3 杀散点 (UI 碎片), close 9x9 x2 把麦田内部的垄沟缝隙合并成一整片.
MORPH_OPEN_SIZE = 3
MORPH_CLOSE_SIZE = 9
MORPH_CLOSE_ITER = 2

# 轮廓过滤: 麦田 ~0.47 filled, 左侧云状噪点 ~0.17; 阈值取 0.35 拉开安全距.
DEFAULT_MIN_AREA = 1000
DEFAULT_MIN_EXTENT = 0.35

# 多边形逼近: eps = 周长 * poly_eps. 0.01 在 1140x655 截图上稳定出 4-6 个角.
DEFAULT_POLY_EPS = 0.01

# 可视化
OVERLAY_ALPHA = 0.4
POLY_COLOR = (0, 0, 255)          # BGR 红, 多边形主轮廓
CORNER_COLOR = (255, 0, 255)      # BGR 紫, 多边形顶点标注
CORNER_RADIUS = 6
CENTER_COLOR = (0, 255, 255)      # BGR 黄
CENTER_RADIUS = 8
TEXT_ORIGIN = (10, 30)
MASK_OVERLAY_BGR = (30, 80, 160)


def _parse_hsv(value: str) -> tuple[int, int, int]:
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"HSV 必须是 3 个逗号分隔整数, 收到 {value!r}"
        )
    try:
        h, s, v = (int(p.strip()) for p in parts)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"HSV 必须是整数: {value!r}") from e
    if not (0 <= h <= 179):
        raise argparse.ArgumentTypeError(f"H 必须在 [0,179], 收到 {h}")
    if not (0 <= s <= 255):
        raise argparse.ArgumentTypeError(f"S 必须在 [0,255], 收到 {s}")
    if not (0 <= v <= 255):
        raise argparse.ArgumentTypeError(f"V 必须在 [0,255], 收到 {v}")
    return (h, s, v)


def _parse_float_unit(value: str) -> float:
    try:
        f = float(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"必须是浮点数: {value!r}") from e
    if not (0.0 < f < 1.0):
        raise argparse.ArgumentTypeError(f"必须在 (0, 1) 范围, 收到 {f}")
    return f


def _parse_pos_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"必须是整数: {value!r}") from e
    if n <= 0:
        raise argparse.ArgumentTypeError(f"必须是正整数, 收到 {n}")
    return n


def detect_color_region(
    image: np.ndarray,
    hsv_lower: tuple[int, int, int],
    hsv_upper: tuple[int, int, int],
    min_area: int = DEFAULT_MIN_AREA,
    min_extent: float = DEFAULT_MIN_EXTENT,
    poly_eps: float = DEFAULT_POLY_EPS,
) -> tuple[
    np.ndarray,
    tuple[int, int, int, int] | None,
    tuple[int, int] | None,
    int,
    np.ndarray | None,
]:
    """HSV 分割 + 形态学 + 过滤 + 多边形拟合.

    Returns:
      mask:    清理后的二值 mask (uint8, 0/255)
      bbox:    (x, y, w, h) 轴对齐, None 表示未找到
      center:  (cx, cy) 轮廓重心, None 表示未找到
      area:    选中轮廓的面积 (int, contourArea)
      polygon: Kx2 int32 ndarray, 顶点按顺时针或逆时针排列; None 表示未找到
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(hsv_lower), np.array(hsv_upper))

    k_open = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (MORPH_OPEN_SIZE, MORPH_OPEN_SIZE)
    )
    k_close = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (MORPH_CLOSE_SIZE, MORPH_CLOSE_SIZE)
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k_open, iterations=1)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, k_close, iterations=MORPH_CLOSE_ITER
    )

    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return mask, None, None, 0, None

    # 按 "面积 > min_area 且 填充率 > min_extent" 过滤.
    # 麦田 extent 约 0.47 (实心平行四边形), 云状噪点 extent 约 0.17; 差约 3x,
    # 这一步是把"最大连通区"从"最大面积的云噪"换成"最大面积的紧致耕地".
    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        bbox_area = w * h
        if bbox_area == 0:
            continue
        if area / bbox_area < min_extent:
            continue
        candidates.append((c, area))

    if not candidates:
        return mask, None, None, 0, None

    field, field_area = max(candidates, key=lambda t: t[1])
    x, y, w, h = cv2.boundingRect(field)

    m = cv2.moments(field)
    if m["m00"] > 0:
        cx = int(m["m10"] / m["m00"])
        cy = int(m["m01"] / m["m00"])
    else:
        cx = x + w // 2
        cy = y + h // 2

    # 在 *原始* 轮廓上 approxPolyDP, 不用 convexHull: 凸包会把内凹缺口(如田块
    # 右侧凸台造成的台阶)填平, 丢失真实形状. 原始轮廓保留凹凸, 得到的 K 边形
    # 更贴合实际边界, 也给后续规划拖动种植路径留下精准角点.
    peri = cv2.arcLength(field, True)
    polygon = cv2.approxPolyDP(field, poly_eps * peri, True).reshape(-1, 2)

    return mask, (x, y, w, h), (cx, cy), int(field_area), polygon


def render_visualization(
    image: np.ndarray,
    mask: np.ndarray,
    bbox: tuple[int, int, int, int],
    center: tuple[int, int],
    area: int,
    polygon: np.ndarray,
) -> np.ndarray:
    overlay = image.copy()
    colored_mask = np.zeros_like(image)
    colored_mask[mask > 0] = MASK_OVERLAY_BGR
    overlay = cv2.addWeighted(overlay, 1.0, colored_mask, OVERLAY_ALPHA, 0)

    cv2.drawContours(overlay, [polygon], 0, POLY_COLOR, 2)
    for i, p in enumerate(polygon):
        cv2.circle(overlay, tuple(p), CORNER_RADIUS, CORNER_COLOR, -1)
        cv2.putText(
            overlay,
            str(i),
            (int(p[0]) + 8, int(p[1]) - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
        )
    cv2.circle(overlay, center, CENTER_RADIUS, CENTER_COLOR, -1)

    cv2.putText(
        overlay,
        f"area={area}  corners={len(polygon)}",
        TEXT_ORIGIN,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        CENTER_COLOR,
        2,
    )
    return overlay


def _load_live() -> np.ndarray:
    win = find_bluestacks()
    if win is None:
        print(
            "错误: 未找到 BlueStacks 窗口, 确认已开且可见.",
            file=sys.stderr,
        )
        sys.exit(2)
    return capture(win)


def _load_from_path(path: Path) -> np.ndarray:
    if not path.exists():
        print(f"错误: 找不到文件 {path}", file=sys.stderr)
        sys.exit(2)
    img = cv2.imread(str(path))
    if img is None:
        print(f"错误: 无法读取图像 {path}", file=sys.stderr)
        sys.exit(2)
    return img


def _resolve_output_path(source_label: str, is_live: bool) -> Path:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    if is_live:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return SNAPSHOTS_DIR / f"live_{stamp}_detected.png"
    stem = Path(source_label).stem
    return SNAPSHOTS_DIR / f"{stem}_detected.png"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HayDay 棕色空地识别 (wheat v1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "snapshot_path",
        nargs="?",
        default=None,
        help="输入截图路径; 与 --live 二选一",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="实时截取 BlueStacks 窗口 (与 snapshot_path 二选一)",
    )
    parser.add_argument(
        "--color",
        choices=sorted(COLOR_PRESETS.keys()),
        default=DEFAULT_COLOR,
        help=f"识别颜色预设 (决定 HSV 默认阈值), 默认 {DEFAULT_COLOR}",
    )
    parser.add_argument(
        "--hsv-lower",
        type=_parse_hsv,
        default=None,
        metavar="H,S,V",
        help="HSV 下界; 若提供则覆盖 --color 预设",
    )
    parser.add_argument(
        "--hsv-upper",
        type=_parse_hsv,
        default=None,
        metavar="H,S,V",
        help="HSV 上界; 若提供则覆盖 --color 预设",
    )
    parser.add_argument(
        "--min-area",
        type=_parse_pos_int,
        default=DEFAULT_MIN_AREA,
        metavar="PIXELS",
        help=f"最小候选面积 (像素), 默认 {DEFAULT_MIN_AREA}",
    )
    parser.add_argument(
        "--min-extent",
        type=_parse_float_unit,
        default=DEFAULT_MIN_EXTENT,
        metavar="RATIO",
        help=f"最小填充率 (contourArea/bboxArea), 默认 {DEFAULT_MIN_EXTENT}",
    )
    parser.add_argument(
        "--poly-eps",
        type=_parse_float_unit,
        default=DEFAULT_POLY_EPS,
        metavar="RATIO",
        help=f"多边形逼近 epsilon 相对周长比例, 默认 {DEFAULT_POLY_EPS}",
    )
    args = parser.parse_args()

    if bool(args.snapshot_path) == bool(args.live):
        parser.error("必须且只能提供 snapshot_path 或 --live 中的一个")

    # 优先级: 显式 --hsv-lower/--hsv-upper > --color 预设
    preset = COLOR_PRESETS[args.color]
    hsv_lower = args.hsv_lower if args.hsv_lower is not None else preset["hsv_lower"]
    hsv_upper = args.hsv_upper if args.hsv_upper is not None else preset["hsv_upper"]

    if args.live:
        image = _load_live()
        out_path = _resolve_output_path("", is_live=True)
    else:
        src_path = Path(args.snapshot_path)
        image = _load_from_path(src_path)
        out_path = _resolve_output_path(str(src_path), is_live=False)

    ih, iw = image.shape[:2]
    mask, bbox, center, area, polygon = detect_color_region(
        image,
        hsv_lower,
        hsv_upper,
        min_area=args.min_area,
        min_extent=args.min_extent,
        poly_eps=args.poly_eps,
    )

    if bbox is None or center is None or polygon is None or area == 0:
        print("no brown region found")
        sys.exit(1)

    vis = render_visualization(image, mask, bbox, center, area, polygon)
    cv2.imwrite(str(out_path), vis)

    print(
        f"center={center}  bbox={bbox}  area={area}  image_size=({iw}, {ih})"
    )
    corners = [tuple(map(int, p)) for p in polygon]
    print(f"polygon ({len(corners)} corners): {corners}")
    print(f"saved: {out_path}")


if __name__ == "__main__":
    main()
