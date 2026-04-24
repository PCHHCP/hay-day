#!/usr/bin/env python3
"""HayDay 抢购菜单栏控制器 (rumps).

和 autobuy/main.py 同进程跑 scan_loop, 勾选要扫的工具子集, 从菜单栏启停.

用法:
  python3 autobuy/menubar.py
"""

import queue
import sys
import threading
from pathlib import Path

import rumps

sys.path.insert(0, str(Path(__file__).parent.parent))

from autobuy.main import NEWSPAPER_TOOLS, scan_loop  # noqa: E402


TITLE_IDLE = "HD: 停"


def _title_running(hits):
    return f"HD: 运行 · {hits}"


class HayDayMenubarApp(rumps.App):
    def __init__(self):
        super().__init__(TITLE_IDLE, quit_button=None)

        # State
        self.worker = None
        self.stop_event = None
        self.hit_count = 0
        self.event_queue = queue.Queue()
        self.running = False  # 是否有活着的 worker

        # Menu items
        self.status_item = rumps.MenuItem(TITLE_IDLE)
        self.status_item.set_callback(None)  # non-clickable label

        self.start_item = rumps.MenuItem("▶ 开始", callback=self.on_start)
        self.stop_item = rumps.MenuItem("■ 停止", callback=self.on_stop)
        self.stop_item.set_callback(None)  # initially disabled

        self.tool_items = {}
        for name in NEWSPAPER_TOOLS:
            item = rumps.MenuItem(name, callback=self.on_toggle_tool)
            item.state = 1
            self.tool_items[name] = item

        self.select_all_item = rumps.MenuItem("全选", callback=self.on_select_all)
        self.select_none_item = rumps.MenuItem("全不选", callback=self.on_select_none)

        # 错误行: title 动态更新, 先隐藏
        self.error_item = rumps.MenuItem("⚠️ ", callback=None)
        self._error_visible = False

        self.quit_item = rumps.MenuItem("退出", callback=rumps.quit_application)

        self.menu = [
            self.status_item,
            None,
            self.start_item,
            self.stop_item,
            None,
            (
                "工具",
                [
                    *self.tool_items.values(),
                    None,
                    self.select_all_item,
                    self.select_none_item,
                ],
            ),
            None,
            self.quit_item,
        ]

        # 启动主线程 drainer, 轮询 worker → UI 事件队列
        self._drainer = rumps.Timer(self._drain_events, 0.2)
        self._drainer.start()

    # ── UI callbacks ─────────────────────────────────────────────

    def on_toggle_tool(self, sender):
        sender.state = 0 if sender.state else 1
        self._refresh_start_enabled()

    def on_select_all(self, _):
        for item in self.tool_items.values():
            item.state = 1
        self._refresh_start_enabled()

    def on_select_none(self, _):
        for item in self.tool_items.values():
            item.state = 0
        self._refresh_start_enabled()

    def on_start(self, _):
        if self.running:
            return
        selected = [name for name, item in self.tool_items.items() if item.state]
        if not selected:
            return

        # 清错误行
        self._hide_error()

        self.hit_count = 0
        self.stop_event = threading.Event()
        self.running = True
        self.title = _title_running(0)
        self.status_item.title = self.title

        # 启动时禁用 start + 工具勾选, 启用 stop
        self.start_item.set_callback(None)
        self.stop_item.set_callback(self.on_stop)
        for item in self.tool_items.values():
            item.set_callback(None)
        self.select_all_item.set_callback(None)
        self.select_none_item.set_callback(None)

        self.worker = threading.Thread(
            target=self._run,
            args=(selected, self.stop_event),
            daemon=True,
        )
        self.worker.start()

    def on_stop(self, _):
        if self.stop_event is not None:
            self.stop_event.set()

    # ── Worker thread ────────────────────────────────────────────

    def _run(self, tools, stop_event):
        def _on_hit(name):
            self.event_queue.put(("hit", name))

        def _on_error(msg):
            self.event_queue.put(("error", msg))

        def _on_ready():
            self.event_queue.put(("ready",))

        try:
            scan_loop(
                tools=tools,
                stop_event=stop_event,
                on_hit=_on_hit,
                on_error=_on_error,
                on_ready=_on_ready,
            )
        except Exception as e:  # 防止 worker 崩溃后 UI 卡在 "运行" 状态
            self.event_queue.put(("error", f"scan_loop 异常: {e}"))
        finally:
            self.event_queue.put(("done",))

    # ── Main-thread drainer ──────────────────────────────────────

    def _drain_events(self, _sender):
        drained = False
        while True:
            try:
                evt = self.event_queue.get_nowait()
            except queue.Empty:
                break
            drained = True
            kind = evt[0]
            if kind == "hit":
                self.hit_count += 1
                new_title = _title_running(self.hit_count)
                self.title = new_title
                self.status_item.title = new_title
            elif kind == "ready":
                self._hide_error()
                new_title = _title_running(self.hit_count)
                self.title = new_title
                self.status_item.title = new_title
            elif kind == "error":
                msg = evt[1]
                self.error_item.title = f"⚠️ {msg}"
                if not self._error_visible:
                    # 把错误行插入到 quit 之前
                    self.menu.insert_before("退出", self.error_item)
                    self._error_visible = True
            elif kind == "done":
                self._on_worker_done()

        # 保险: 如果 worker 已挂掉但没走到 done 事件, 也复位
        if (
            not drained
            and self.running
            and self.worker is not None
            and not self.worker.is_alive()
        ):
            self._on_worker_done()

    def _on_worker_done(self):
        self.running = False
        self.worker = None
        self.stop_event = None
        self.title = TITLE_IDLE
        self.status_item.title = TITLE_IDLE

        self.start_item.set_callback(self.on_start)
        self.stop_item.set_callback(None)
        for item in self.tool_items.values():
            item.set_callback(self.on_toggle_tool)
        self.select_all_item.set_callback(self.on_select_all)
        self.select_none_item.set_callback(self.on_select_none)

        self._refresh_start_enabled()

    # ── Helpers ──────────────────────────────────────────────────

    def _refresh_start_enabled(self):
        if self.running:
            return
        any_selected = any(item.state for item in self.tool_items.values())
        if any_selected:
            self.start_item.set_callback(self.on_start)
        else:
            self.start_item.set_callback(None)

    def _hide_error(self):
        if self._error_visible:
            try:
                del self.menu["⚠️ "]
            except KeyError:
                # rumps 用 item.title 作 key, title 可能已变成 "⚠️ xxx"
                for key in list(self.menu.keys()):
                    if key.startswith("⚠️"):
                        del self.menu[key]
                        break
            self._error_visible = False
            self.error_item.title = "⚠️ "


def main():
    HayDayMenubarApp().run()


if __name__ == "__main__":
    main()
