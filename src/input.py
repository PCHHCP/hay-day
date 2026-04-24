"""点击注入: 通过 Android Debug Bridge 发 input tap.

BlueStacks Air (Apple Silicon) + macOS 26 上 Quartz CGEvent 两种模式 (PID/全局)
都被系统拦或静默丢弃; 走 adb 是最稳的路径, 事件直接进 Android 输入栈,
不依赖 macOS 权限, 也不触碰 mac 鼠标.

前置条件:
  1) BlueStacks 设置 → 高级 → 打开 Android 调试桥 (默认端口 5555)
  2) Mac 装好 adb: brew install android-platform-tools
"""

import atexit
import re
import subprocess


_TARGET = None   # "host:port"
_SCREEN = None   # (android_width, android_height)
_SHELL = None    # 常驻 `adb shell` Popen, 避免每次 tap 都 fork 新进程


def _run(args, timeout=5):
    """统一的 adb 调用. 返回 (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            ["adb", *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "找不到 adb 命令. 安装: `brew install android-platform-tools`"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"adb {' '.join(args)} 超时") from e
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def init(port=5555, host="127.0.0.1"):
    """建立 adb 连接, 查分辨率, 缓存为全局状态.
    返回 (target, (width, height)).
    """
    global _TARGET, _SCREEN
    target = f"{host}:{port}"

    out, err, rc = _run(["version"])
    if rc != 0:
        raise RuntimeError(f"adb version 失败: {err or out}")

    out, err, _ = _run(["connect", target])
    if "connected" not in (out + err).lower():
        raise RuntimeError(
            f"adb connect {target} 失败: {out} {err}\n"
            "检查 BlueStacks 是否开启了 ADB (设置 → 高级 → Android 调试桥)"
        )

    out, _, _ = _run(["devices"])
    online = any(
        line.split()[:2] == [target, "device"]
        for line in out.splitlines() if line.split()
    )
    if not online:
        raise RuntimeError(
            f"adb devices 里 {target} 不在线:\n{out}\n"
            "可能 BlueStacks 的 ADB 未启用或端口不对"
        )

    out, err, _ = _run(["-s", target, "shell", "wm", "size"])
    m = re.search(r"(\d+)\s*x\s*(\d+)", out)
    if not m:
        raise RuntimeError(f"解析 wm size 失败: {out!r} / {err!r}")

    _TARGET = target
    _SCREEN = (int(m.group(1)), int(m.group(2)))
    _open_shell()
    return target, _SCREEN


def _open_shell():
    """拉起常驻 adb shell. 每次 tap 只写一行 `input tap X Y` 进 stdin,
    省掉 adb 二进制启动 + server 握手 (~100-300ms) 的开销.
    """
    global _SHELL
    _close_shell()
    _SHELL = subprocess.Popen(
        ["adb", "-s", _TARGET, "shell"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )


def _close_shell():
    global _SHELL
    if _SHELL is None:
        return
    try:
        if _SHELL.stdin and not _SHELL.stdin.closed:
            _SHELL.stdin.close()
        _SHELL.terminate()
    except Exception:
        pass
    _SHELL = None


atexit.register(_close_shell)


def tap(img_x, img_y, image_size):
    """经 adb input tap 点击. 图像像素坐标按比例转 Android 屏幕坐标.

    自动兼容旋转: BlueStacks `wm size` 返回的常是纵屏物理尺寸
    (1080x1920), 但游戏窗口显示的是横屏. 若截图和 Android 屏幕
    方向相反, 交换宽高再做坐标换算.

    返回 (android_x, android_y).
    """
    if _TARGET is None or _SCREEN is None:
        raise RuntimeError("adb 未初始化, 先调用 init()")
    iw, ih = image_size
    aw, ah = _SCREEN
    if (iw > ih) != (aw > ah):
        aw, ah = ah, aw
    ax = int(round(img_x * aw / iw))
    ay = int(round(img_y * ah / ih))

    cmd = f"input tap {ax} {ay}\n".encode()
    if _SHELL is None or _SHELL.poll() is not None:
        _open_shell()
    try:
        _SHELL.stdin.write(cmd)
        _SHELL.stdin.flush()
    except (BrokenPipeError, OSError) as e:
        print(f"[WARN] adb shell 管道断开, 重连: {e}", flush=True)
        _open_shell()
        try:
            _SHELL.stdin.write(cmd)
            _SHELL.stdin.flush()
        except Exception as e2:
            print(f"[WARN] adb tap 重试失败: {e2}", flush=True)
    return ax, ay


def swipe(img_x1, img_y1, img_x2, img_y2, image_size, duration_ms=300):
    """经 adb input swipe 做按住-拖动. 像素坐标按比例换算到 Android 屏幕坐标.

    用途: HayDay 种植/收割手势需要按住作物图标后拖过田地,
    input swipe 会模拟 ACTION_DOWN → MOVE → UP, 是触发拖动批量种/收的标准方式.

    参数:
      img_x1, img_y1  : 起点 (图像像素坐标)
      img_x2, img_y2  : 终点 (图像像素坐标)
      image_size      : (iw, ih) 截图像素尺寸 (与 tap 一致)
      duration_ms     : 滑动时长毫秒. HayDay 需要 "按住" 语义,
                        太短 (<150ms) Android 会判为 fling/tap, 不触发拖动.

    返回 ((ax1, ay1), (ax2, ay2)) Android 屏幕坐标起止点.
    """
    if _TARGET is None or _SCREEN is None:
        raise RuntimeError("adb 未初始化, 先调用 init()")
    iw, ih = image_size
    aw, ah = _SCREEN
    if (iw > ih) != (aw > ah):
        aw, ah = ah, aw
    ax1 = int(round(img_x1 * aw / iw))
    ay1 = int(round(img_y1 * ah / ih))
    ax2 = int(round(img_x2 * aw / iw))
    ay2 = int(round(img_y2 * ah / ih))

    cmd = f"input swipe {ax1} {ay1} {ax2} {ay2} {int(duration_ms)}\n".encode()
    if _SHELL is None or _SHELL.poll() is not None:
        _open_shell()
    try:
        _SHELL.stdin.write(cmd)
        _SHELL.stdin.flush()
    except (BrokenPipeError, OSError) as e:
        print(f"[WARN] adb shell 管道断开, 重连: {e}", flush=True)
        _open_shell()
        try:
            _SHELL.stdin.write(cmd)
            _SHELL.stdin.flush()
        except Exception as e2:
            print(f"[WARN] adb swipe 重试失败: {e2}", flush=True)
    return (ax1, ay1), (ax2, ay2)
