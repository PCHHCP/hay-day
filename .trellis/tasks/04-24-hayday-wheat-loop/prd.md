# HayDay 自动种麦子（单次执行）

## 目标 (Goal)

在 macOS + BlueStacks 环境下，实现 HayDay 游戏小麦田的「识别 → 种植 → 等待 → 收割」**单次执行**脚本（**不循环**——仓库容量限制，循环留待「上架卖出」模块完成后再做）。复用现有抢购脚本积累的底层能力（窗口定位、截图、模板匹配、adb 点击注入），按子目录隔离，**不破坏抢购脚本**。

## 运行环境

- 与 autobuy 相同：macOS 26 + BlueStacks Air，Python 3.11+，ADB 5555 端口
- 复用依赖：`mss`、`opencv-python`、`numpy`、`pyobjc-framework-Quartz`

## 核心架构决策

| 决策点 | 选择 | 原因 |
|---|---|---|
| 目录隔离 | `wheat/` 子目录，与 `autobuy/` 平级，共享 `src/` | 互不污染，autobuy 可继续维护 |
| Phase 0：autobuy 重构 | 把根目录的 `autobuy.py` + `templates/` + `snapshots/` 整体搬入 `autobuy/` 子目录 | 让两个模块对称，未来加 `selling/` 同样模式 |
| Git baseline | 搬迁前 `git init` + 首次 commit | 提供回滚能力 |

## 目录结构（目标）

```
hayday/
├── src/                          # 共享底层 (不动)
│   ├── window.py                 # BlueStacks 窗口定位 + 截图
│   ├── vision.py                 # 多尺度模板匹配
│   └── input.py                  # adb 点击注入
├── capture_template.py           # 通用工具，加 --module 参数控制输出位置
├── requirements.txt
├── autobuy/                      # 抢购模块（Phase 0 搬入）
│   ├── __init__.py
│   ├── main.py                   # 原根目录 autobuy.py
│   ├── templates/
│   └── snapshots/
└── wheat/                        # 本任务新增
    ├── __init__.py
    ├── main.py
    ├── templates/
    └── snapshots/
```

## 已确认的事实

- **田地布局**：单块倾斜矩形网格（HayDay 2.5D 等距视角，平行四边形），由许多小垄格拼成
- **田地数量**：仅一片麦田
- **视角**：跑脚本期间用户保证不拖动地图（视角固定，可缓存识别结果）
- **识别策略**：**HSV 颜色分割**（弃用栅栏/角桩模板匹配 —— 栅栏遍布整个农场，模板不唯一）
  - 棕色空地像素在画面里独一份（周围绿地/红屋顶/白栅栏对比强烈）
  - 成熟麦田是金黄色，也可靠地不同于画面其他元素
- **网格尺寸**：随等级增长可变 —— 无需精确识别，mask 的 bounding box 会自动适配
- **部分已种场景**：收割中途退出后重跑，画面里会有棕色+绿色混合 —— HSV 棕色 mask 恰好只命中未种区域
- **种植/收割手势**：按住 + 拖动一气呵成；只要手指按住目标作物在田里拖动就能批量种/收
- **棕色田地** = 已耕作待种植状态

## 流程规格（单次执行，不循环）

```
1. 启动: adb 初始化, 找 BlueStacks 窗口
2. HSV 棕色 mask → 最大连通区 → 拿到 "棕色空地" 的重心 + bbox
3. 点击重心 → 弹出作物选择菜单
4. 模板匹配「小麦图标」 → 点击之，进入"按住小麦"状态
5. 在 bbox 内从上到下做 N 次水平 swipe（手指只会在棕色像素上划过，已种区域不受影响）→ 种植完成
6. time.sleep(种植等待秒数) — 纯计时，从种完瞬间起算
7. HSV 金色 mask → 最大连通区 → 拿到 "成熟麦田" 的重心 + bbox
8. 点击重心 → 弹出收割工具菜单
9. 模板匹配「镰刀图标」 → 点击之
10. 在 bbox 内从上到下做 N 次水平 swipe → 收割完成
11. 退出 (用户手动收尾「上架」)
```

## 决策记录 (来自 brainstorm)

| 决策点 | 选择 | 备注 |
|---|---|---|
| 田地识别 | **HSV 颜色分割 + 最大连通区 + bbox** | 弃用栅栏角桩模板（栅栏遍布农场，模板不唯一） |
| 田地几何输出 | `(center_xy, bbox_xywh)` 两个值 | 不推算菱形 4 角，bbox 足以规划 swipe 路径 |
| 拖动手势 | 多次单行 `adb input swipe`（直线两点） | 简单可靠，预计 2 秒种完整片 |
| 等待策略 | 纯计时 `time.sleep(N)`，从种植完成瞬间起算 | 不做视觉确认 |
| 终止 | 单次执行后退出，无循环 | 仓库容量限制，循环等卖出模块完成 |
| 菜单内图标定位 | 模板匹配（菜单弹出位置可能受地图位置影响） | 小麦/镰刀各 1 张模板 |

后续阶段（不在本任务范围）：
- 上架卖出（货摊 / 报纸广告）

## 硬约束

1. **不破坏 autobuy**：除 Phase 0 的搬迁与路径调整外，autobuy 业务逻辑零修改
2. **不修改 `src/` 已有函数**：如需新能力（如滑动），新增函数（如 `input.swipe()`），不改 `input.tap()` 签名
3. **wheat 自包含**：所有 wheat 专用模板/快照/中间产物只在 `wheat/` 子目录内
4. **可恢复**：搬迁前必须有 git baseline，能 `git reset` 回滚

## 实现细节默认值（已确认）

| 配置 | 默认值 | 暴露为 CLI 参数 |
|---|---|---|
| 等待成熟秒数 | 130 秒 | `--wait 130` |
| 平行 swipe 行数 | 8 行（超采样保证覆盖） | `--rows 8` |
| 单次 swipe 持续时长 | 300 ms | （硬编码常量，必要时改） |
| 点击田地后等菜单延时 | 400 ms | （硬编码） |
| 选工具后等"按住"模式生效 | 200 ms | （硬编码） |
| swipe 之间间隔 | 100 ms | （硬编码） |
| ADB 端口 | 5555 | `--adb-port 5555` |
| 失败处理 | 任何识别失败立即报错退出（非零返回码） | 不重试 |

## 验收标准

### Phase 0：autobuy 目录重构（前置工作，不破坏现有抢购）
- [ ] `git init` + baseline commit（提供回滚点）
- [ ] `autobuy.py` → `autobuy/main.py`，`templates/` → `autobuy/templates/`，`snapshots/` → `autobuy/snapshots/`
- [ ] 加 `autobuy/__init__.py`
- [ ] 修正 `autobuy/main.py` 的 `sys.path`（指向项目根，让 `from src import ...` 仍可用）
- [ ] 删除根目录残留的 `__pycache__/`
- [ ] 烟雾测试：`python3 autobuy/main.py --help` 输出正常；空跑（不连 BlueStacks 也行）能成功加载所有模板

### Phase 1：capture_template.py 改造 + wheat 骨架 + HSV 调参
- [x] 给 `capture_template.py` 加 `--module {autobuy,wheat}` 参数，控制 snapshot/template 写入位置
- [x] 创建 `wheat/__init__.py`、`wheat/templates/`、`wheat/snapshots/`（空目录占位用 `.gitkeep`）
- [ ] 用户抓 2 张模板（`wheat_icon.png` + `sickle_icon.png`），自匹配置信度 ≥ 0.95
- [ ] 写 `wheat/tune_hsv.py`：拖滑杆实时预览掩膜，在真实截图上调出 **棕色空地** 和 **金色成熟麦** 两组 HSV 阈值
- [ ] 确认的阈值写入 `wheat/field_detect.py` 作为模块常量

### Phase 2：底层能力扩展
- [ ] `src/input.py` 新增 `swipe(x1, y1, x2, y2, image_size, duration_ms=300)` 函数（不修改 `tap()` 签名）
- [ ] swipe 函数复用现有的常驻 `adb shell` 进程，避免 fork 开销
- [ ] 单元测试：手动调一次 swipe，BlueStacks 中能看到拖动轨迹

### Phase 3：wheat 主流程
- [ ] `wheat/field_detect.py`：`detect_unplanted(img)` / `detect_ripe(img)`，各返回 `(center_xy, bbox_xywh, mask)`；掩膜经过面积过滤 + 最大连通区
- [ ] `wheat/main.py` 实现端到端流程（识别 → 种 → 等 → 收 → 退出）
- [ ] 田地识别成功后打印 bbox + center 便于调试，并把掩膜 overlay 保存到 `wheat/snapshots/_mask_<stage>.png`
- [ ] 种植阶段：在 bbox 内 N 次水平 swipe 完成，过程有日志
- [ ] 等待阶段：显示倒计时（每 10 秒打一次日志）
- [ ] 收割阶段：与种植对称
- [ ] 任意阶段失败：打印错误位置 + 当时截图保存到 `wheat/snapshots/error_<timestamp>.png` + 退出非零

### Phase 4：端到端验证
- [ ] 在 BlueStacks 中真实跑一次完整流程，麦子被全部种上 + 全部收割
- [ ] autobuy 回归测试：`python3 autobuy/main.py` 跑一次，确认抢购功能未受影响

## Brainstorm 状态

- [x] 全部决策已敲定，进入实施

## 执行计划（按 Phase 顺序）

1. **Phase 0** — autobuy 目录重构（git init + 文件迁移 + 烟雾测试）
2. **Phase 1** — capture_template.py 加参数 + wheat 骨架 + 用户抓模板
3. **Phase 2** — `src/input.py` 加 swipe
4. **Phase 3** — `wheat/main.py` 主流程
5. **Phase 4** — 端到端验证（含 autobuy 回归）

## Brainstorm 状态

- [x] 问题 1：项目位置与代码复用 → 选 A（hayday/ 内子目录隔离 + 共享 src/）
- [x] 追加：autobuy 也搬进子目录 → 选 A（纳入本任务 Phase 0）
- [x] 问题 2：田地布局确认 → 单块菱形，视角固定，网格尺寸可变
- [x] 问题 3：菱形 4 角识别 → 4 模板各匹配一次（A）
- [x] 问题 4：拖动手势 → 多次单行 `adb input swipe`（A）
- [x] 问题 5：等待策略 → 纯计时（A）
- [x] 问题 6：终止 → 单次执行不循环
- [ ] 问题 7：剩余细节（等待秒数、swipe 行间距、菜单延时）

## 待捕获模板清单（用户在 Phase 1 用 capture_template.py 抓）

| 名称 | 用途 | 备注 |
|---|---|---|
| `wheat_icon.png` | 作物菜单中的小麦图标 | 点田地后弹出的圆形菜单里 |
| `sickle_icon.png` | 收割工具菜单中的镰刀 | 点成熟田地后弹出的菜单里 |

**田地本身不需要模板** —— 靠 `wheat/tune_hsv.py` 调出的 HSV 阈值识别（棕色空地 + 金色成熟麦）。
