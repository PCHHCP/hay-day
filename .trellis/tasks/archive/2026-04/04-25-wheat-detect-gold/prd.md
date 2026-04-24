# HayDay 金色成熟麦田识别（wheat detect gold）

## 目标 (Goal)

在 `wheat/detect.py` 基础上, 通过**抽出颜色配置 + CLI 加 `--color` 开关**, 支持"金色成熟麦田"识别, 与已稳定的"棕色空地"识别共用同一条管道. 金色 HSV 阈值已实测固化, 形态学/过滤/多边形参数完全复用.

## 背景

上一任务 `04-24-hayday-wheat-loop` (已归档) 完成棕色空地识别 (HSV+形态学+extent 过滤+polygon 拟合). 本任务扩展到**金色成熟**状态, 为后续"识别成熟→自动收割"循环铺路.

**关键实测结论 (2026-04-25)**:
- 在 `wheat/snapshots/gold_field.png` (1432×840, 整片成熟) 采样 25 个金色像素:
  - H 范围 22~28 (mean 26.2), S 183~255 (mean 242), V 243~255 (mean 252)
  - 边缘/阴影金色最低 V=196
- 用阈值 `(18,150,180)~(32,255,255)` + **现有** 形态学/extent/poly_eps 跑 `detect.py`:
  - 红色多边形 (8 corners) 紧贴金色田块边界 (含右下凸台)
  - 中心点 (730,399) 在田内, area=467426
  - 未误抓画面内其它金黄元素 (向日葵/邮箱铃铛) — 被 min_area=1000 过滤
- **结论**: 金色与棕色识别的唯一差异是 HSV 阈值, 其它参数零调整

## 范围

### 本次做
- 抽出颜色配置结构 (两组常量: 棕色 / 金色)
- `detect.py` 加 CLI 参数 `--color brown|gold` (默认 `brown`, 保持向后兼容)
- 用户传 `--hsv-lower/--hsv-upper` 时仍可覆盖 color 预设
- 固化 `wheat/snapshots/gold_field.png` + `wheat/snapshots/gold_field_detected.png` 作为金色回归基准
- `brown_field.png` 跑出的结果不变 (回归通过)

### 本次不做
- 金色 + 棕色**同时检测** (画面同一时间只有一种颜色是主导, 不需要多色并行)
- 成熟度分级 (半熟/全熟) — 按约束, 只在 "全熟" 时触发收割, 等价于 "金色整块识别到"
- 把识别接到收割动作
- 实时 `--live` 金色测试 (若有需要, 用户本地自测即可, 走同一 CLI)
- 抽象未来作物 (玉米/南瓜) — YAGNI, 加第 3 种颜色时再重构

## 目录结构

```
wheat/
├── __init__.py            (不改)
├── detect.py              ← 本次修改
├── snapshots/
│   ├── brown_field.png              (已有, 不改)
│   ├── brown_field_detected.png     (已有, 会被重跑覆盖, 内容应不变)
│   ├── gold_field.png               (已有, 作为金色基准输入)
│   └── gold_field_detected.png      ← 本次生成, 作为金色基准输出
└── templates/.gitkeep     (不改)
```

## 脚本契约

### CLI

```bash
# 默认行为 = 棕色 (向后兼容, v1 调用不变)
python3 -m wheat.detect <snapshot_path>
python3 -m wheat.detect --live

# 显式指定颜色
python3 -m wheat.detect <path> --color brown
python3 -m wheat.detect <path> --color gold

# 仍然可手动覆盖 HSV (优先级: --hsv-* > --color 预设)
python3 -m wheat.detect <path> --color gold --hsv-lower 20,150,180
```

### 输出

格式与 v1 一致, 无变化:
```
center=(x, y)  bbox=(x, y, w, h)  area=N  image_size=(W, H)
polygon (K corners): [(x,y), ...]
saved: <path>
```

控制台**不**打印当前用的 color (保持输出对 downstream 解析稳定); 如有需要可以加 stderr 日志, 但本次不做.

## 颜色配置

用模块级**常量字典** (不建类), 命名清晰即可:

```python
COLOR_PRESETS = {
    "brown": {
        "hsv_lower": (8, 150, 130),
        "hsv_upper": (15, 255, 210),
    },
    "gold": {
        "hsv_lower": (18, 150, 180),
        "hsv_upper": (32, 255, 255),
    },
}
```

- 形态学/面积/extent/poly_eps 参数**不进预设**, 保留为模块级默认常量, 两种颜色共用 (实测金色场景完全不需要调这些).
- 如果未来某种颜色确实需要不同形态学 kernel, 再把 preset 升级成完整 dict; 现在不做.

## 验收标准

1. **棕色文字输出回归 (必须通过)**:
   ```bash
   python3 -m wheat.detect wheat/snapshots/brown_field.png
   python3 -m wheat.detect wheat/snapshots/brown_field.png --color brown
   ```
   两条命令控制台输出 `center=(510, 250)  bbox=(38, 11, 943, 502)  area=227188` 与 v1 完全一致. **不重跑 `brown_field_detected.png` 图像文件** (允许保持 v1 生成版, 避免 approxPolyDP 浮点微差导致字节不一致).

2. **金色识别命中**:
   ```bash
   python3 -m wheat.detect wheat/snapshots/gold_field.png --color gold
   ```
   - 输出 `center` 在 bbox 内, area > 100000
   - polygon 有 ≥4 个顶点, 肉眼检查红框紧贴金色田块边界 (含右下凸台)
   - 未把向日葵/邮箱铃铛等画面内小金黄元素纳入主轮廓
   - 生成的 `gold_field_detected.png` 符合上述描述

3. **CLI 覆盖优先级**:
   ```bash
   python3 -m wheat.detect wheat/snapshots/gold_field.png --color gold --hsv-lower 0,0,0 --hsv-upper 179,255,255
   ```
   mask 应该几乎覆盖全图 (证明手动 HSV 覆盖 preset 生效).

4. **默认行为兼容**:
   - 不传 `--color` = 等价于 `--color brown` = v1 行为
   - 下游调用 `python3 -m wheat.detect <path>` 的代码 (如 autobuy 文档或后续循环任务) 无需修改

5. **autobuy 不受影响**: `python3 -m autobuy.main` 正常启动.

## 硬约束

1. **不改 `src/`**
2. **不动 `autobuy/`**
3. **核心函数改名**: `detect_brown_region()` → `detect_color_region()`. 签名保持一致 (只改名, 不加/删参数), 行为一致. 该函数目前只被 CLI main 调用, 改名不破坏下游.
4. **不新增依赖**
5. **不写 `--color` 之外的新 CLI 标志** (比如 `--dual` / `--classify`) — YAGNI

## 技术默认值

沿用 v1:

| 项 | 默认 |
|---|---|
| open kernel | 3×3 ellipse, iter=1 |
| close kernel | 9×9 ellipse, iter=2 |
| min_area | 1000 |
| min_extent | 0.35 |
| poly_eps | 0.01 |
| mask 可视化色 | BGR (30, 80, 160) |
| polygon 色 | 红 (0,0,255) |
| center 色 | 黄 (0,255,255) |
| 输出命名 | `<basename>_detected.png` |

## 后续任务 (不在本次)

1. `src/input.py` 加 `drag_path(points, image_size, duration_ms)`, 基于 `adb shell input motionevent DOWN/MOVE/UP`
2. 完整循环: 棕色全空检测 → 拖动种植 → 等待 → 金色成熟检测 → 收割 → 回到棕色
3. 触发条件: 识别面积 ≥ 全空/全熟基准的 XX% 阈值 (具体系数循环任务再定)
