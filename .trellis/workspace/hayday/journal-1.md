# Journal - hayday (Part 1)

> AI development session journal
> Started: 2026-04-24

---



## Session 1: wheat 模块 v1: 棕色空地识别（调参至稳定命中）

**Date**: 2026-04-25
**Task**: wheat 模块 v1: 棕色空地识别（调参至稳定命中）
**Branch**: `dev`

### Summary

新建 wheat/detect.py 做 HayDay 棕色耕地识别，从初始默认 HSV 命中整屏杂物，逐步收敛到 HSV=(8,150,130)~(15,255,210) + ellipse 形态学 + extent 过滤 + raw-contour 多边形逼近。最终在真实截图上 6 边形严丝合缝贴合麦田（含右侧凸台）。未 commit，待用户再测几张不同田地状态截图后提交。

### Main Changes

## 背景

- 当前 session 继续 `04-24-hayday-wheat-loop` 任务（原 PRD 方向错，已删除重写）
- 原方案种植动作用多次 `adb input swipe` ——每次 swipe 都 touch-down/up，"按住作物"语义会丢失。正确语义：**一次 touch-down → 任意路径 → touch-up**
- 本次任务范围缩窄为**只识别**，种植动作留给下个任务用 `adb shell input motionevent DOWN/MOVE/UP` 实现

## 识别调参过程（关键数据）

### 问题初现

初始默认 HSV `(10,60,40)~(25,255,200)` 在真实截图 `wheat/snapshots/brown_field.png` 上跑出来红框覆盖大半屏——把麦田、树、木箱、UI 全框进去。

### 诊断：像素采样

| 位置 | BGR | HSV |
|---|---|---|
| 麦田（5 个点）| ~(33,80,172) | **H=10-12, S=200-210, V=160-190** |
| 非麦田棕色（木箱/装饰）| 变化大 | H=11-40, S=125-255, V=125-245 |

关键发现：麦田 HSV 聚集非常紧，默认阈值太宽松。

### 形态学误导

单纯收紧 HSV 后 mask 显示麦田是**条纹状**（每一条垄是白，垄沟是黑）。`close 5×5 iter=2` 不足以合并垄成整块；换 `close 15×15 iter=3` 又桥接了麦田周围的云状零散噪点，最大连通区还是错的。

### 最终收敛参数

| 参数 | 值 | 动机 |
|---|---|---|
| HSV lower | (8, 150, 130) | 只保留饱和度高、亮度中段的橙棕 |
| HSV upper | (15, 255, 210) | 排除 H>15 的道具/UI |
| Kernel 形状 | MORPH_ELLIPSE | 圆盘状结构元不产生轴向毛刺 |
| open | 3×3 iter=1 | 精准杀散点 |
| close | 9×9 iter=2 | 合并垄沟但不桥接邻近噪点 |
| min_area | 1000 px | 排除碎片 |
| **min_extent** | **0.35** | **麦田 ~0.47 vs 云噪 ~0.17，差 3x，关键过滤** |
| poly_eps | 0.01 × 周长 | approxPolyDP on raw contour，自适应 4-6 点 |

### 边框形状迭代

1. v1: 轴对齐 bbox → 不贴合倾斜田形
2. v5A: `minAreaRect` → 强制 90° 角，和等距平行四边形不匹配，含草地空白
3. v5B: `approxPolyDP(convexHull, 4 pts)` → 逼近成 4 边形，但凸包把右侧**凸台**填平
4. **v7: `approxPolyDP(raw contour, eps_frac=0.01)` → 6 点紧贴真实边界，含凸台**

## 最终输出

真实截图：
```
center=(536, 368)  bbox=(293, 248, 512, 241)  area=58716  image_size=(1140, 655)
polygon (6 corners): [(293,360), (552,488), (734,396), (770,407), (804,393), (518,248)]
```

## 新建文件

- `wheat/__init__.py`（空包标记）
- [wheat/detect.py](wheat/detect.py)（核心检测，290 行）
- `wheat/templates/.gitkeep`

## 未提交的工作

- `wheat/` 整个目录
- `.trellis/tasks/04-24-hayday-wheat-loop/` PRD 重写 + jsonl

## 未完成

- 用户计划测试更多田地状态（部分种过、成熟中、空田、不同地图缩放等）验证鲁棒性
- 满意后 `/trellis:finish-work` → commit → 正式归档

## 关键决策记录（给下个会话参考）

1. **macOS CGEvent 在 BlueStacks Air 被拦/丢弃**（`src/input.py` 注释证实）——所有鼠标/触屏都必须走 adb
2. **种植动作不能用 adb input swipe 分段**——每次 swipe 都抬手掉作物。正确方案：`adb shell input motionevent DOWN/MOVE/UP` 实现一次按住 + 多点路径 + 抬手
3. **凸包会抹平内凹**——对带凸台/缺口的田地必须在 *原始轮廓* 上 approxPolyDP，不用 convexHull
4. **extent（填充率）是区分「紧凑田」vs「云状噪点」的关键单指标**，差约 3 倍

## 下一个任务（建议）

金色成熟麦田识别：
- 复用 `detect.py` 架构
- 换 HSV 阈值（需要实测金色像素）
- 同套形态学 + extent 过滤 + 多边形逼近
- 可以直接把 detect.py 泛化成 `detect_color_region(image, hsv_lower, hsv_upper, ...)`

再下一个：`src/input.py` 新增 `drag_path(points, image_size, duration_ms)`，基于 `adb shell input motionevent` 实现连续拖动。


### Git Commits

(No commits - planning session)

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: wheat v1 识别: 多场景回归 + 基准固化 + 归档

**Date**: 2026-04-25
**Task**: wheat v1 识别: 多场景回归 + 基准固化 + 归档
**Branch**: `dev`

### Summary

(Add summary)

### Main Changes

### Summary
继续上次 session, 实时跑 `python3 -m wheat.detect --live` 验证多场景鲁棒性. 最终在纯棕空地 / 缩放 / 棕绿混合 三种状态下确认行为符合预期, 替换回归基准图后固化提交并 archive 任务.

### Key Decisions / Changes

| 项 | 结果 |
|---|---|
| 纯棕空地 (live) | 6 顶点贴合, center 在田内, 命中精确 |
| 缩放后 (live) | 用户本地验证通过, 无需参数调整 |
| 棕绿混合 (已种一半) | 只框中间残留棕色, **按约束预期不触发**, 非 bug |
| 回归基准 | 旧 `brown_field.png` 丢失, 用户手动截了一张精选纯棕 (988x584), 替换为新基准, 跑出 area=227188 / 6-corner polygon 完美贴合 |
| 产物策略 | `.gitignore` 加 `wheat/snapshots/live_*.png`, 只入库 `brown_field.png` + `brown_field_detected.png` 作回归参考 |
| `wheat/templates/` | 添加 `.gitkeep` 占位 (下一阶段模板匹配用) |

### Architectural Decision: 不做 outline + plantable 双层

用户明确: 棕绿混合时识别不到整块 **不是 bug**. 下一步种植策略 = **只在全空田触发** (面积 ≥ 全棕基准的阈值). 理由: 保持识别单一职责 (纯棕 HSV), 种植逻辑不用处理 "哪些格子能点" 的子问题. 已固化到 project memory.

### Constraints Captured (memory)

- **麦田连片连接**: 所有田块合为单一 blob, 识别只取最大连通区, 不做多 blob 处理
- **种植触发=全空**: 棕绿混合态 = "还不能种"信号, 而非覆盖失败

### Files Committed (c66d4fa)

- `wheat/__init__.py`
- `wheat/detect.py` (290 行, 核心不变)
- `wheat/snapshots/brown_field.png` (新基准, 988x584)
- `wheat/snapshots/brown_field_detected.png` (期望输出)
- `wheat/templates/.gitkeep`
- `.gitignore` (+1 规则)
- `.trellis/tasks/04-24-hayday-wheat-loop/` (PRD 重写 + jsonl)
- `.trellis/workspace/hayday/` (index + journal-1)

Pushed to `origin/dev` (`9261156..c66d4fa`).

### Excluded

- `autobuy/菜单栏运行脚本` (49 字节备忘, 属 menubar 任务, 故意不 stage)

### Next Tasks (suggested)

1. **金色成熟麦田识别** — 复用 `detect.py` 架构, 换 HSV 区间 (实测金色像素), 同套形态学 + extent 过滤
2. **`src/input.py` 加 `drag_path(points, image_size, duration_ms)`** — 基于 `adb shell input motionevent DOWN/MOVE/UP`, 一次按住连续路径, 解决 "每次 swipe 都掉作物" 问题
3. **完整循环** — 识别棕→点中心→选小麦→拖路径种植→等待→识别金→收割, 触发条件遵循 "全空地才种" 约束


### Git Commits

| Hash | Message |
|------|---------|
| `c66d4fa` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: wheat: 金色成熟麦田识别 (共用管道 + --color 预设)

**Date**: 2026-04-25
**Task**: wheat: 金色成熟麦田识别 (共用管道 + --color 预设)
**Branch**: `dev`

### Summary

(Add summary)

### Main Changes

### Summary
扩展 `wheat/detect.py` 支持金色成熟麦田识别. 在真实截图上采样金色像素 HSV, 发现 HayDay 美术做得非常饱和 (H 22~28, S 183~255, V 243~255), 与担心的"稀疏纹理"相反, 纯 HSV 分割就够用. 抽出 `COLOR_PRESETS` 字典 + `--color brown|gold` CLI, 形态学/extent/poly_eps 全部共用零调整.

### Key Changes

| 项 | 结果 |
|---|---|
| 核心函数改名 | `detect_brown_region` → `detect_color_region` (签名不变) |
| 颜色预设 | 模块级字典 `COLOR_PRESETS = {"brown": ..., "gold": ...}` |
| CLI 新增 | `--color brown\|gold` 默认 brown, `--hsv-*` 优先级覆盖 preset |
| brown 回归 | 文字 + 图像**字节级一致**, 与 v1 零差异 |
| gold 命中 | area=467426, 8 顶点贴合金田 (含右下凸台), 未误抓向日葵/邮箱铃铛 |
| 基准固化 | `wheat/snapshots/gold_field.png` + `gold_field_detected.png` 入库 |

### Non-obvious Findings

1. **成熟麦田在 HayDay 里是整片高饱和金**, 不是绿棕穿插的稀疏纹理 — 事前猜测"需要更大 close kernel"被证伪. 下次扩新作物仍建议先采样再拍参数.
2. **`brown_field_detected.png` 重跑字节级一致** — approxPolyDP 在固定输入上完全确定性, 不用为"图像漂移"担心 (PRD 里的担心被数据否定).
3. **向日葵 + 邮箱铃铛虽金黄但面积 < 1000 px**, 现有 `min_area=1000` 就过滤掉了, 不用单独处理.

### Files Committed (9aac129)

- `wheat/detect.py` (+COLOR_PRESETS, +--color CLI, 改名)
- `wheat/snapshots/gold_field.png` (基准输入, 1432x840)
- `wheat/snapshots/gold_field_detected.png` (基准输出)
- `.trellis/tasks/04-25-wheat-detect-gold/` (PRD + task.json)

Pushed to `origin/dev` (`1e649a0..9aac129`), 随后 archive 任务.

### Next Tasks

1. **`src/input.py` 加 `drag_path(points, image_size, duration_ms)`** - 基于 `adb shell input motionevent DOWN/MOVE/UP`, 解决"一次按住作物连续拖动路径"的底层能力 (swipe 会抬手掉作物)
2. **完整循环** — 识别棕→判断全空→拖动种植→等待 2 分钟→识别金→收割→回到棕. 触发条件遵循 "全空/全熟" 约束 (面积 ≥ 基准阈值)


### Git Commits

| Hash | Message |
|------|---------|
| `9aac129` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
