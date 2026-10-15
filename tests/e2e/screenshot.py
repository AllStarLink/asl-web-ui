#!/usr/bin/python3
"""Screenshots of asl-web-ui pages with headless Firefox over WebDriver BiDi.

    tests/e2e/screenshot.py URL OUT.png [--cookie NAME=VALUE] [--wait 3]
                            [--size 1280x820] [--dark] [--insecure]
                            [--click CSS-SELECTOR ...] [--eval JS]

Starts Firefox with a throwaway profile, optionally sets a cookie (e.g. a
session from a scripted login), opens URL, waits for data to load, and
saves a PNG. Browser console messages (including Content-Security-Policy
violations) are printed. --insecure accepts self-signed certificates.
Needs only Firefox and python3-aiohttp.
"""

import argparse
import asyncio
import base64
import os
import shutil
import socket
import subprocess
import tempfile
from urllib.parse import urlsplit

import aiohttp


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BiDi:
    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0
        self.events: list[dict] = []

    async def drain(self, seconds: float) -> None:
        """Collect events for a while (e.g. console messages while a page loads)."""
        try:
            async with asyncio.timeout(seconds):
                while True:
                    msg = await self.ws.receive_json()
                    if msg.get("type") == "event":
                        self.events.append(msg)
        except TimeoutError:
            pass

    async def call(self, method: str, params: dict) -> dict:
        self.next_id += 1
        await self.ws.send_json({"id": self.next_id, "method": method, "params": params})
        while True:
            msg = await self.ws.receive_json()
            if msg.get("type") == "event":
                self.events.append(msg)
                continue
            if msg.get("id") == self.next_id:
                if msg.get("type") == "error":
                    raise RuntimeError(f"{method}: {msg.get('message')}")
                return msg["result"]


async def capture(url: str, out: str, cookie: str | None, wait: float, size: str, dark: bool, insecure: bool,
                  clicks: list[str] | None = None, js: str | None = None) -> None:
    width, height = (int(x) for x in size.split("x"))
    port = free_port()
    profile = tempfile.mkdtemp(prefix="asl-ff-")
    with open(os.path.join(profile, "user.js"), "w") as f:
        f.write('user_pref("ui.systemUsesDarkTheme", %d);\n' % (1 if dark else 0))
        f.write('user_pref("layout.css.prefers-color-scheme.content-override", %d);\n' % (0 if dark else 1))
    env = {**os.environ, "HOME": profile}
    proc = subprocess.Popen(
        ["firefox", "--headless", "--no-remote", "--profile", profile, f"--remote-debugging-port={port}",
         "--window-size", f"{width},{height}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )
    try:
        async with aiohttp.ClientSession() as http:
            for _ in range(100):
                try:
                    ws = await http.ws_connect(f"ws://127.0.0.1:{port}/session")
                    break
                except aiohttp.ClientError:
                    await asyncio.sleep(0.2)
            else:
                raise RuntimeError("Firefox did not open its remote debugging port")
            bidi = BiDi(ws)
            await bidi.call("session.new", {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": insecure}}})
            await bidi.call("session.subscribe", {"events": ["log.entryAdded"]})
            tree = await bidi.call("browsingContext.getTree", {})
            ctx = tree["contexts"][0]["context"]
            await bidi.call("browsingContext.setViewport", {"context": ctx, "viewport": {"width": width, "height": height}})
            if cookie:
                name, value = cookie.split("=", 1)
                host = urlsplit(url).hostname
                await bidi.call("storage.setCookie", {"cookie": {
                    "name": name, "value": {"type": "string", "value": value}, "domain": host, "path": "/",
                    "secure": url.startswith("https:"),
                }})
            await bidi.call("browsingContext.navigate", {"context": ctx, "url": url, "wait": "complete"})
            await bidi.drain(wait)
            for selector in clicks or []:
                res = await bidi.call("script.evaluate", {"target": {"context": ctx}, "awaitPromise": False,
                    "expression": f"(() => {{ const el = document.querySelector({selector!r}); if (!el) return 'missing'; el.click(); return 'clicked'; }})()"})
                print(f"click {selector}: {res.get('result', {}).get('value')}")
                await bidi.drain(1.0)
            if js:
                res = await bidi.call("script.evaluate", {"target": {"context": ctx}, "awaitPromise": False, "expression": js})
                print("eval:", res.get("result", {}).get("value"))
            shot = await bidi.call("browsingContext.captureScreenshot", {"context": ctx})
            with open(out, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            for ev in bidi.events:
                entry = ev.get("params", {})
                print(f"console {entry.get('level', '?')}: {entry.get('text', '')}")
            await ws.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("out")
    p.add_argument("--cookie")
    p.add_argument("--wait", type=float, default=3.0)
    p.add_argument("--size", default="1280x820")
    p.add_argument("--dark", action="store_true")
    p.add_argument("--insecure", action="store_true")
    p.add_argument("--click", action="append")
    p.add_argument("--eval")
    a = p.parse_args()
    asyncio.run(capture(a.url, a.out, a.cookie, a.wait, a.size, a.dark, a.insecure, a.click, a.eval))
    print(f"wrote {a.out}")
