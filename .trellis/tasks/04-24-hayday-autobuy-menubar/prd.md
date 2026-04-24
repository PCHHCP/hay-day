# HayDay 抢购菜单栏控制器 (rumps)

## Goal

给现有的 [autobuy/main.py](../../../autobuy/main.py) 抢购脚本加一个 macOS 菜单栏 app 作为控制层，让用户可以：

1. 勾选要抢购的工具子集（1 个 / 多个 / 全选）
2. 从菜单栏启动/停止抢购循环
3. 在菜单栏看到运行状态和命中次数

## Background

- `autobuy/main.py` 当前写死扫全部 6 种工具（nail/bolt/screw/panel/plank/tape）
- 最终形态是 mac app 操控，不是 CLI
- 选型：rumps（Python 菜单栏框架）——与脚本同 Python 栈，同进程调用 `scan_loop`，用 `threading.Event` 控制启停，零 IPC

## Requirements

### 功能性

- **工具选择**：菜单里 6 个工具各有一个勾选项，✅/◻️ 切换
  - 支持"全选"和"全不选"快捷项
  - 至少要勾一个才能开始
- **启停**：
  - "▶ 开始" → 后台线程跑 `scan_loop`，入参是当前勾选的工具列表
  - "■ 停止" → `threading.Event.set()`，让循环干净退出
- **状态显示**：菜单栏图标/标题反映状态（空闲 / 运行中）
- **运行日志**：菜单内显示最近一次命中（工具名 + 时间）和累计命中数

### 非功能性

- 单文件 app，入口 `autobuy/menubar.py`
- 不破坏现有 CLI 入口 `python3 -m autobuy.main` 的行为
- `scan_loop` 重构成接受参数的函数：`scan_loop(tools, stop_event, on_hit=callback, ...)`
- CLI 入口薄壳化，调用同一个 `scan_loop`

## Acceptance Criteria

- [ ] `rumps` 已加入 [requirements.txt](../../../requirements.txt)
- [ ] `autobuy/menubar.py` 运行后在菜单栏出现图标
- [ ] 菜单展开可见 6 个工具的勾选项、全选/全不选、▶/■、状态行
- [ ] 勾选子集后点开始，脚本只扫选中的模板（验证：日志里只出现选中的工具）
- [ ] 点停止后循环在 ≤1s 内退出
- [ ] `scan_loop(tools=...)` 能通过 CLI (`python3 -m autobuy.main --tools nail,bolt`) 也能通过 menubar 调用
- [ ] 已有 CLI 行为不变（不传 `--tools` 默认全选）

## Decisions (brainstorm 已确认)

- **勾选状态不持久化**，每次启动默认全选 6 个工具
- **菜单栏标题**：文字状态，`HD: 停` / `HD: 运行 · 3`（3 = 累计命中数）
- **错误展示**：菜单内增加 `⚠️ <错误>` 行，不弹系统通知
- **高级参数不暴露**：`cooldown` / `interval` / `adb-port` 全部写死默认值，YAGNI

## Technical Notes

- rumps 主线程必须是 UI 线程，`scan_loop` 要开 `threading.Thread(daemon=True)` 跑
- `scan_loop` 内部 `while True` 改成 `while not stop_event.is_set()`
- 命中回调 `on_hit(tool_name)` 用 `rumps.Timer` 或主线程回调更新菜单，避免跨线程改 UI
- 勾选状态存内存即可（持久化视 Open Question 定）

## Out of Scope

- 全局快捷键（非必要）
- 日志文件持久化（stdout 够用）
- 通知中心集成（除非错误展示需要）
- 打包成 .app / 签名公证（先 `python3 autobuy/menubar.py` 跑起来再说）
