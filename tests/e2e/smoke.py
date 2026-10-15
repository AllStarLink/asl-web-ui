#!/usr/bin/python3
"""End-to-end smoke test against an installed asl-web-ui.

Logs in with a real account through the web server, then checks the
session, system and status endpoints, the live-status WebSocket, the Asterisk
console, CSRF/origin enforcement and logout.

    tests/e2e/smoke.py https://localhost:8443/asl-web-ui/ USER PASSWORD_FILE [--insecure]

--insecure skips TLS certificate verification (self-signed test certificates).
The password is read from a file so it never appears on a command line.
"""

import argparse
import asyncio
import json
import ssl
import sys

import aiohttp

OK = "\033[32mPASS\033[0m"
BAD = "\033[31mFAIL\033[0m"
failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"{OK if condition else BAD}  {name}{'' if condition else f'  ({detail})'}")
    if not condition:
        failures += 1


async def main(base: str, user: str, password: str, verify: bool) -> int:
    base = base.rstrip("/") + "/"
    origin = base.split("/asl-web-ui")[0] if "/asl-web-ui" in base else base.rstrip("/")
    tls: ssl.SSLContext | bool = True if verify else False
    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(cookie_jar=jar, connector=aiohttp.TCPConnector(ssl=tls)) as http:
        api = base + "api/v1/"
        headers = {"Origin": origin}

        async with http.post(api + "auth/login", json={"user": user}, headers=headers) as r:
            step = await r.json()
        check("login starts a PAM conversation", step.get("state") == "prompt", json.dumps(step))
        async with http.post(api + f"auth/login/{step.get('id')}", json={"answer": "wrong-password"}, headers=headers) as r:
            bad = await r.json()
        check("wrong password is refused generically", bad.get("state") == "failure" and "Check your user name" in bad.get("message", ""), json.dumps(bad))

        async with http.post(api + "auth/login", json={"user": user}, headers=headers) as r:
            step = await r.json()
        async with http.post(api + f"auth/login/{step.get('id')}", json={"answer": password}, headers=headers) as r:
            step = await r.json()
            cookie = r.headers.get("Set-Cookie", "")
        check("correct password logs in", step.get("state") == "success", json.dumps(step))
        check("session cookie is Secure, HttpOnly, SameSite=Strict",
              all(x in cookie for x in ("Secure", "HttpOnly", "SameSite=Strict")), cookie)
        csrf = step.get("session", {}).get("csrf", "")
        headers = {"Origin": origin, "X-CSRF-Token": csrf}

        async with http.get(api + "auth/session") as r:
            session = await r.json()
        check("session reports the user", session.get("user") == user, json.dumps(session))

        async with http.get(api + "system") as r:
            system = await r.json()
        check("system info", r.status == 200 and bool(system.get("hostname")), json.dumps(system))

        async with http.get(api + "status") as r:
            status = await r.json()
        check("status reaches Asterisk", status.get("asterisk", {}).get("reachable") is True, json.dumps(status)[:300])
        check("status lists nodes", isinstance(status.get("nodes"), list) and len(status["nodes"]) > 0, json.dumps(status.get("nodes")))

        async with http.ws_connect(api + "ws/events", headers={"Origin": origin}) as ws:
            msg = await asyncio.wait_for(ws.receive_json(), 15)
        check("events socket pushes status", msg.get("type") == "status", str(msg)[:200])

        try:
            await http.ws_connect(api + "ws/events", headers={"Origin": "https://evil.example"})
            check("events socket refuses a foreign origin", False, "connected")
        except aiohttp.WSServerHandshakeError as exc:
            check("events socket refuses a foreign origin", exc.status == 403, str(exc.status))

        async with http.ws_connect(api + "ws/console", headers={"Origin": origin}) as ws:
            await ws.send_str(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
            await ws.send_str(json.dumps({"type": "input", "data": "rpt show version\r"}))
            seen = b""
            try:
                while b"app_rpt version" not in seen:
                    m = await asyncio.wait_for(ws.receive(), 15)
                    if m.type != aiohttp.WSMsgType.BINARY:
                        break
                    seen += m.data
            except asyncio.TimeoutError:
                pass
        check("console runs Asterisk CLI commands", b"app_rpt version" in seen, seen[-300:].decode(errors="replace"))
        check("status reports configuration state", "rpt_errors" in status.get("config", {}), json.dumps(status.get("config")))

        # Manual Config Edit, read-only: nothing here writes to /etc/asterisk.
        async with http.get(api + "config/files") as r:
            files = (await r.json()).get("files", [])
        check("config file list", r.status == 200 and any(f["name"] == "rpt.conf" and f["exists"] for f in files),
              json.dumps(files)[:300])
        async with http.get(api + "config/files/rpt.conf") as r:
            rpt = await r.json()
        check("reads rpt.conf", r.status == 200 and "[nodes]" in rpt.get("content", ""), str(r.status))
        async with http.post(api + "config/files/rpt.conf/check", json={"content": "x = 1\n[a]\n"}, headers=headers) as r:
            found = await r.json()
        check("checks a draft without saving it", r.status == 200 and found.get("counts", {}).get("error") == 1,
              json.dumps(found)[:300])
        async with http.get(api + "config/files/..%2Fpasswd") as r:
            check("refuses files outside the list", r.status == 404, str(r.status))

        # Nodes, read-only: a plan is computed but never applied.
        async with http.get(api + "nodes") as r:
            nodes = await r.json()
        check("node list", r.status == 200 and len(nodes.get("nodes", [])) > 0, str(nodes)[:300])
        first = nodes["nodes"][0]["number"] if nodes.get("nodes") else "1999"
        async with http.post(api + "nodes/plan", json={"op": "callsign", "node": first, "callsign": "N0CALL",
                                                      "replace_custom": True}, headers=headers) as r:
            plan = await r.json()
        check("plans a node change without applying it", r.status == 200 and
              ("unchanged" in plan or any("idrecording" in f["diff"] for f in plan.get("files", []))), str(plan)[:300])
        async with http.post(api + "nodes/plan", json={"op": "add", "number": "12345"}, headers=headers) as r:
            bad = await r.json()
        check("node number validation", r.status == 400 and bad.get("field") == "number", str(bad)[:200])

        async with http.post(api + "auth/logout", json={}, headers={"Origin": origin, "X-CSRF-Token": "wrong"}) as r:
            check("missing/wrong CSRF token is refused", r.status == 403, str(r.status))

        async with http.post(api + "auth/logout", json={}, headers=headers) as r:
            check("logout", r.status == 200, str(r.status))
        async with http.get(api + "auth/session") as r:
            check("session is gone after logout", (await r.json()).get("user") is None)
        async with http.get(api + "status") as r:
            check("API refuses requests after logout", r.status == 401, str(r.status))

    print(f"\n{'All checks passed' if not failures else f'{failures} check(s) failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("user")
    parser.add_argument("password_file")
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()
    with open(args.password_file) as f:
        pw = f.read().strip()
    sys.exit(asyncio.run(main(args.base, args.user, pw, not args.insecure)))
