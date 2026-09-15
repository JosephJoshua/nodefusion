
from __future__ import annotations

import base64
import json
import os
import platform
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


class CdpError(Exception):
    pass



_PLAYWRIGHT_GLOBS = ("chromium*/chrome-win/chrome.exe",
                     "chromium*/chrome-linux/chrome",
                     "chromium*/chrome-mac/Chromium.app/Contents/MacOS/Chromium")


def _playwright_dirs() -> list[Path]:
    out = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(Path(local) / "ms-playwright")
    home = Path.home()
    out.append(home / "Library" / "Caches" / "ms-playwright")   # macOS
    out.append(home / ".cache" / "ms-playwright")               # Linux
    return out


def _candidates() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("NF_CHROME")
    if env:
        out.append(Path(env))

    for pw in _playwright_dirs():
        if not pw.is_dir():
            continue
        for pat in _PLAYWRIGHT_GLOBS:
            out.extend(sorted(pw.glob(pat), reverse=True))

    system = platform.system()
    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA")
        for base in filter(None, [os.environ.get("PROGRAMFILES"),
                                  os.environ.get("PROGRAMFILES(X86)"),
                                  local]):
            out.append(Path(base) / "Google/Chrome/Application/chrome.exe")
            out.append(Path(base) / "Microsoft/Edge/Application/msedge.exe")
    elif system == "Darwin":
        for app, exe in (("Google Chrome", "Google Chrome"),
                         ("Chromium", "Chromium"),
                         ("Microsoft Edge", "Microsoft Edge"),
                         ("Brave Browser", "Brave Browser")):
            leaf = f"{app}.app/Contents/MacOS/{exe}"
            out.append(Path("/Applications") / leaf)
            out.append(Path.home() / "Applications" / leaf)
    else:
        for p in ("/usr/bin", "/usr/local/bin", "/opt/google/chrome",
                  "/snap/bin"):
            for name in ("google-chrome", "google-chrome-stable", "chromium",
                         "chromium-browser", "chrome", "microsoft-edge"):
                out.append(Path(p) / name)

    for name in ("chrome", "chromium", "chromium-browser", "google-chrome",
                 "google-chrome-stable", "msedge", "microsoft-edge"):
        w = shutil.which(name)
        if w:
            out.append(Path(w))
    return out


def find_browser() -> Path:
    for p in _candidates():
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    exe = {"Windows": "chrome.exe",
           "Darwin": "'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'",
           }.get(platform.system(), "google-chrome")
    raise CdpError(
        "找不到可用的 Chrome / Chromium。导出视频需要一个 Chromium 内核浏览器。\n"
        f"  可以设环境变量 NF_CHROME 指向可执行文件（本机形如 {exe}），\n"
        "  或安装 Chrome / Edge，或用 playwright 缓存里的 chromium。")


# ---------------------------------------------------------------- WebSocket

class _WebSocket:

    def __init__(self, url: str, timeout: float = 120.0):
        m = re.match(r"^ws://([^:/]+):(\d+)(/.*)$", url)
        if not m:
            raise CdpError(f"无法解析 WebSocket 地址：{url}")
        host, port, path = m.group(1), int(m.group(2)), m.group(3)

        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._buf = b""
        self.broken = False

        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())

        while b"\r\n\r\n" not in self._buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise CdpError("WebSocket 握手时连接被关闭")
            self._buf += chunk
        head, self._buf = self._buf.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if "101" not in status:
            raise CdpError(f"WebSocket 握手失败：{status}")


    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            try:
                chunk = self.sock.recv(1 << 20)
            except TimeoutError as e:
                self.broken = True
                raise CdpError(
                    f"WebSocket 读取超时（等了 {self.sock.gettimeout():.0f}s）；"
                    "浏览器可能被机器负载拖住了") from e
            if not chunk:
                raise CdpError("WebSocket 连接被对端关闭")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        head = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head.append(0x80 | n)
        elif n < (1 << 16):
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        self.sock.sendall(bytes(head) + masked)

    def _read_frame(self) -> tuple[int, bytes]:
        b0, b1 = self._recv_exact(2)
        fin = b0 & 0x80
        opcode = b0 & 0x0F
        if b1 & 0x80:
            raise CdpError("服务端不应该发送掩码帧")
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._recv_exact(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._recv_exact(8))[0]
        return (opcode if fin else -opcode - 1), self._recv_exact(n)


    def send_text(self, s: str) -> None:
        self._send_frame(0x1, s.encode("utf-8"))

    def recv_text(self) -> str:
        parts: list[bytes] = []
        while True:
            op, data = self._read_frame()
            cont = op < 0
            real = (-op - 1) if cont else op
            if real == 0x8:                        # close
                raise CdpError("浏览器关闭了 CDP 连接")
            if real == 0x9:                        # ping
                self._send_frame(0xA, data)
                continue
            if real == 0xA:                        # pong
                continue
            parts.append(data)
            if not cont:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass



class Browser:

    def __init__(self, width: int = 1600, height: int = 900, scale: float = 1.0,
                 exe: Path | None = None, timeout: float = 600.0):
        self.exe = Path(exe) if exe else find_browser()
        self.width, self.height, self.scale = width, height, scale
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self.ws: _WebSocket | None = None
        self.session: str | None = None
        self._id = 0
        self._tmp = Path(tempfile.mkdtemp(prefix="nf-cdp-"))


    def start(self) -> None:
        argv = [
            str(self.exe),
            "--headless=new",
            "--remote-debugging-port=0",
            f"--user-data-dir={self._tmp}",
            f"--window-size={self.width},{self.height}",
            "--hide-scrollbars",
            "--force-device-scale-factor=" + str(self.scale),
            "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--disable-background-networking",
            "--disable-sync", "--mute-audio",
            "--allow-file-access-from-files",
            "--no-sandbox",
            "--disable-gpu",
            "--run-all-compositor-stages-before-draw",
            "--disable-dev-shm-usage",
            "about:blank",
        ]
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        port = self._wait_port()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=30) as r:
            ver = json.load(r)
        self.ws = _WebSocket(ver["webSocketDebuggerUrl"], timeout=self.timeout)

        t = self.cmd("Target.createTarget", {"url": "about:blank"})
        a = self.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})
        self.session = a["sessionId"]

        self.cmd("Page.enable")
        self.cmd("Runtime.enable")
        self.cmd("Emulation.setDeviceMetricsOverride", {
            "width": self.width, "height": self.height,
            "deviceScaleFactor": self.scale, "mobile": False,
        })

    def _wait_port(self, limit: float = 60.0) -> int:
        f = self._tmp / "DevToolsActivePort"
        end = time.time() + limit
        while time.time() < end:
            if self.proc and self.proc.poll() is not None:
                raise CdpError(f"浏览器启动即退出（退出码 {self.proc.returncode}）：{self.exe}")
            if f.is_file():
                txt = f.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                if txt and txt[0].isdigit():
                    return int(txt[0])
            time.sleep(0.05)
        raise CdpError(f"等待 {limit:.0f}s 仍未拿到 Chrome 调试端口：{self.exe}")

    def close(self) -> None:
        if self.ws:
            try:
                self.cmd("Browser.close", session=False, timeout=10)
            except Exception:
                pass
            self.ws.close()
            self.ws = None
        if self.proc:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        shutil.rmtree(self._tmp, ignore_errors=True)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.close()


    def cmd(self, method: str, params: dict | None = None, *,
            session: bool = True, timeout: float | None = None) -> dict:
        assert self.ws is not None
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        if session and self.session:
            msg["sessionId"] = self.session
        self.ws.send_text(json.dumps(msg))

        end = time.time() + (timeout or self.timeout)
        while True:
            if time.time() > end:
                raise CdpError(f"CDP 命令超时：{method}")
            reply = json.loads(self.ws.recv_text())
            if reply.get("id") != self._id:
                continue
            if "error" in reply:
                raise CdpError(f"CDP {method} 失败：{reply['error']}")
            return reply.get("result", {})


    def navigate(self, url: str) -> None:
        self.cmd("Page.navigate", {"url": url})

    def eval(self, expr: str, await_promise: bool = False):
        r = self.cmd("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": await_promise,
        })
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            desc = (d.get("exception") or {}).get("description") or d.get("text")
            raise CdpError(f"页面里执行 JS 出错：{desc}")
        return r.get("result", {}).get("value")

    def wait_for(self, expr: str, limit: float = 180.0, poll: float = 0.2):
        end = time.time() + limit
        while time.time() < end:
            try:
                v = self.eval(expr)
                if v:
                    return v
            except CdpError:
                pass
            time.sleep(poll)
        raise CdpError(f"等待条件超时（{limit:.0f}s）：{expr}")

    def screenshot(self) -> bytes:
        r = self.cmd("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": False,
            "fromSurface": True,
        })
        return base64.b64decode(r["data"])
