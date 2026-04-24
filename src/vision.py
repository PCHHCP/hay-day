"""目标检测: 多尺度模板匹配"""

import cv2


DEFAULT_SCALES = (0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20)


def match_template(image, template, threshold=0.8, scales=DEFAULT_SCALES):
    """多尺度模板匹配.
    返回 dict {x, y, score, scale, box=(x,y,w,h)} 或 None.
    (x, y) 是匹配中心在 image 中的像素坐标.

    必须扫完所有尺度, 取最高分, 否则擦边过阈值的错尺度会把中心点算偏,
    点击落在空白上.
    """
    ih, iw = image.shape[:2]
    best = None

    for s in scales:
        th = int(round(template.shape[0] * s))
        tw = int(round(template.shape[1] * s))
        if th < 8 or tw < 8 or th > ih or tw > iw:
            continue
        scaled = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(image, scaled, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if best is None or max_val > best["score"]:
            best = {
                "x": max_loc[0] + tw // 2,
                "y": max_loc[1] + th // 2,
                "score": float(max_val),
                "scale": float(s),
                "box": (max_loc[0], max_loc[1], tw, th),
            }

    if best is None or best["score"] < threshold:
        return None
    return best


def draw_detection(image, result, label=None, color=(0, 255, 0)):
    """在图上画出检测框和中心点, 返回新图."""
    vis = image.copy()
    x, y, w, h = result["box"]
    cv2.rectangle(vis, (x, y), (x + w, y + h), color, 3)
    cv2.circle(vis, (result["x"], result["y"]), 6, (0, 0, 255), -1)
    if label:
        cv2.putText(
            vis,
            label,
            (x, max(y - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2,
        )
    return vis
