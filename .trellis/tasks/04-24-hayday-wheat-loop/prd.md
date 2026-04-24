# HayDay 棕色空地识别（wheat 模块 v1）

## 目标 (Goal)

在 `wheat/` 目录下做一个**棕色空地识别**的实验脚本。输入一张游戏截图（或实时截屏），输出标注识别结果的可视化 PNG + 控制台打印 `(center, bbox)`。

目的是**验证识别策略是否可靠**，本次不接入任何操作流程（不种、不收、不点）。

## 背景

- `autobuy/` 已有完整的抢购脚本（窗口定位、截图、模板匹配、adb tap/swipe）
- 下一步想做 HayDay 麦田自动化（识别 → 种 → 等 → 收 → 卖）
- 用户担心田地识别不准确，所以**拆出独立实验脚本先验证识别**，不急着做种植
- 种植动作涉及「按住作物不抬手 + 任意路径拖动」，旧设想用多次 adb swipe 有问题（每次 swipe 都抬手掉作物），后续会用 `adb shell input motionevent DOWN/MOVE/UP` 实现连续拖动——**本任务不做**

## 范围

### 本次做
- 棕色空地识别（未种植的耕地）
- 可视化调试输出
- 支持从已存 PNG 读入，也支持实时截 BlueStacks

### 本次不做
- 金色成熟麦田识别
- 种植 / 收割动作
- 作物菜单里的小麦图标匹配
- motionevent 连续拖动（底层能力）
- 循环 / 等待逻辑

## 目录结构

```
hayday/
├── src/                    (不改)
│   ├── window.py
│   ├── vision.py
│   └── input.py
├── capture_template.py     (不改, 已支持 --module wheat)
├── autobuy/                (完全不动)
└── wheat/                  ← 新增
    ├── __init__.py
    ├── detect.py           ← 本次核心
    ├── templates/          (空, 留给下次)
    └── snapshots/          (capture_template.py 自动写入)
```

## 脚本契约

### CLI

```bash
# 从已存 PNG 读
python3 -m wheat.detect <snapshot_path>

# 实时截 BlueStacks 当前窗口
python3 -m wheat.detect --live

# 调 HSV 阈值
python3 -m wheat.detect <path> --hsv-lower 10,60,40 --hsv-upper 25,255,200
```

### 输出

1. **控制台**：
   ```
   center=(x, y)  bbox=(x, y, w, h)  area=N pixels  image_size=(W, H)
   ```
   若未找到棕色区域，打印 `no brown region found` 并以非零码退出。

2. **可视化 PNG**：保存到 `wheat/snapshots/<basename>_detected.png`
   - 原图
   - 半透明棕色 mask 叠加（比如 alpha 0.4）
   - 红框 bbox
   - 黄点 center
   - 左上角文字注释 `area=N`

## 识别策略（v1）

- HSV 颜色分割
- 形态学开闭（去噪 + 填洞）
- 最大连通区 → `cv2.boundingRect` + 重心

### HSV 默认阈值

先给一组 HayDay 棕色耕地的**经验初始值**（实现时基于截图实测再微调）：

- Lower: `H=10, S=60, V=40`
- Upper: `H=25, S=255, V=200`

阈值暴露为 CLI 参数 `--hsv-lower H,S,V --hsv-upper H,S,V`，用户可肉眼调参。

### 形态学参数

- Kernel: 5×5 矩形
- Open 1 次（去掉零散棕色像素，如栅栏柱影子）
- Close 2 次（填充种植过的垄沟间隙）
- 参数先硬编码，不够用再 CLI 化

## 验收标准

1. **快照回归**：拿一张真实的 HayDay 棕色空地截图（放到 `wheat/snapshots/`），跑 `python3 -m wheat.detect wheat/snapshots/<name>.png`
2. 生成 `wheat/snapshots/<name>_detected.png`，红框正好包住棕色耕地（可接受小毛边）
3. 控制台打印的 `center`、`bbox`、`area` 合理（center 在 bbox 内，area > 0）
4. 调 `--hsv-lower/upper` 能让识别结果明显变化（证明参数生效）
5. `python3 -m autobuy.main` 照常能跑（autobuy 零影响）

## 硬约束

1. **不改 `src/` 已有函数**（本次也不需要加新函数）
2. **不动 `autobuy/`**
3. **`wheat/` 自包含**：所有 wheat 专用代码/模板/快照都在 `wheat/` 子目录
4. **不引入新依赖**：只用现有的 `opencv-python`、`numpy`、`mss`、`pyobjc-framework-Quartz`
5. **不上 adb input**：本任务不 import `src.input`

## 技术默认值

| 项 | 默认 |
|---|---|
| 可视化 alpha | 0.4 |
| bbox 颜色 | BGR (0, 0, 255) 红 |
| center 颜色 | BGR (0, 255, 255) 黄，半径 8 |
| 文字位置 | 左上 (10, 30) |
| 输出文件命名 | `<input_basename>_detected.png` |
| --live 模式保存名 | `live_YYYYMMDD_HHMMSS_detected.png` |

## 后续任务（不在本次）

1. 金色成熟麦田识别（复用 detect.py 架构，换 HSV 区间）
2. `src/input.py` 新增 `drag_path(points, image_size, duration_ms)` 基于 `adb shell input motionevent` 实现连续拖动
3. 作物菜单里的小麦 / 镰刀图标模板匹配
4. 完整流程：识别 → 点击棕色中心 → 选小麦 → 拖动种植 → 等待 → 识别成熟 → 收割
