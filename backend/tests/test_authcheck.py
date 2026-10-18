"""Parsing asl-node-auth-check's text output (until its --json mode exists)."""

from asl_web_ui import authcheck

FULL = """
-----===== AllStarLink Node Authentication Check =====-----

Checking configuration:
      Info: Skipping evaluation of private node 1999
      Info: rpt.conf has configuration for: 2701, 2702
      Info: /etc/asterisk/iax.conf contains no registration lines.
      Info: /etc/asterisk/rpt_http_registrations.conf contains 2 registration line(s)
      Info: Registrations present for configured node(s): 2701, 2702
      Info: IP from https://conntest-east1.allstarlink.org/ip reports: 203.0.113.7
      Info: IP from https://conntest-west1.allstarlink.org/ip reports: 203.0.113.7
   Warning: IP test to https://conntest-west2.allstarlink.org/ip failed
      Info: IP from udp://conntest-east1.allstarlink.org:4570 reports: 203.0.113.7
      Info: IP from udp://conntest-west1.allstarlink.org:4569 reports: 203.0.113.7
      Info: IP from udp://conntest-west2.allstarlink.org:4569 reports: 203.0.113.7
        OK: HTTP IP probes have consensus on the same perceived IP
        OK: IAX IP probes have consensus on the same perceived IP

Testing node 2701:
        OK: Node registration config is well-formed
        OK: Node registration type is HTTP
        OK: register.allstarlink.org is reachable (via HTTP)
        OK: HTTP registration state is Registered
        OK: Perceived IAX IP:PORT for this node is: 203.0.113.7:4569
        OK: Registered to register-east - 192.0.2.10
        OK: Server-set UDP port matches bindport in iax.conf
        OK: Node registration within 10 minutes: 2026-10-15 06:01:02
      Info: Last time IP changed was 2026-10-01 12:00:00 UTC
        OK: Incoming connections to IAX from other nodes is successful
      Info: IAX ping test has a roundtrip time of 42ms
        OK: No problems detected with node 2701

Testing node 2702:
        OK: Node registration config is well-formed
        OK: Node registration type is HTTP
        OK: register.allstarlink.org is reachable (via HTTP)
     Error: HTTP registration state is Rejected
      Info: Stopping node checks due to registration failure
      Info: as further information will be unreliable

     Error: Node 2702 has 1 error(s)!
"""

ABORTED = """
-----===== AllStarLink Node Authentication Check =====-----

Checking configuration:
      Info: Skipping evaluation of private node 1999
      Info: rpt.conf has configuration for:
      Info: /etc/asterisk/iax.conf contains no registration lines.
      Info: /etc/asterisk/rpt_http_registrations.conf contains 1 registration line(s)
      Info: Registrations present for configured node(s): 1234
     Error: No configuration present for registrations for node(s): 1234
     Error: Cannot continue; reconcile configuration before proceeding
"""


def test_full_run_sections_and_ids():
    r = authcheck.parse_text(FULL)
    assert [(s["id"], s["node"]) for s in r["sections"]] == [
        ("config", None), ("public_ip", None), ("node", "2701"), ("node", "2702")]
    assert r["result"] == "error"
    assert all(f["id"] != "unknown" for s in r["sections"] for f in s["findings"])
    config = r["sections"][0]["findings"]
    assert config[1] == {"id": "config.nodes", "level": "info", "message": "rpt.conf has configuration for: 2701, 2702",
                         "data": {"nodes": ["2701", "2702"]}}
    public = r["sections"][1]["findings"]
    assert public[2]["id"] == "public_ip.http_probe" and public[2]["level"] == "warning"
    n1 = {f["id"]: f for f in r["sections"][2]["findings"]}
    assert n1["node.perceived_address"]["data"] == {"address": "203.0.113.7:4569"}
    assert n1["node.registrar"]["data"] == {"name": "register-east", "ip": "192.0.2.10"}
    assert r["sections"][2]["complete"] is True
    n2 = r["sections"][3]
    assert n2["complete"] is False
    assert {"id": "node.registration_state", "level": "error", "message": "HTTP registration state is Rejected",
            "data": {"type": "HTTP", "state": "Rejected"}} in n2["findings"]


def test_aborted_run():
    r = authcheck.parse_text(ABORTED)
    assert r["result"] == "aborted"
    ids = [f["id"] for f in r["sections"][0]["findings"]]
    assert "config.missing_configuration" in ids and "config.cannot_continue" in ids
    assert r["counts"]["error"] == 2


async def test_run_uses_text_mode_without_json(tmp_path):
    tool = tmp_path / "asl-node-auth-check"
    tool.write_text("#!/bin/sh\ncat <<'EOF'\n" + ABORTED + "EOF\n")
    tool.chmod(0o755)
    r = await authcheck.run(str(tool))
    assert r["result"] == "aborted" and "raw" in r and r["exit_code"] == 0


async def test_run_executes_tool_once(tmp_path):
    # The real tool ignores its arguments; probing it with --help ran a whole
    # second check and got the real one rate-limited by nodeping (#27).
    count = tmp_path / "count"
    tool = tmp_path / "asl-node-auth-check"
    tool.write_text(f"#!/bin/sh\necho x >> {count}\ncat <<'EOF'\n" + ABORTED + "EOF\n")
    tool.chmod(0o755)
    await authcheck.run(str(tool))
    assert count.read_text().count("x") == 1


async def test_run_prefers_json_mode(tmp_path):
    tool = tmp_path / "asl-node-auth-check"
    tool.write_text('#!/bin/sh\n# accepts --json\n'
                    'echo \'{"schema": 1, "result": "ok", "counts": {}, "sections": []}\'\n')
    tool.chmod(0o755)
    r = await authcheck.run(str(tool))
    assert r["result"] == "ok" and "raw" not in r


def test_text_data_matches_json_fields():
    # The ids and data the --json mode gives (docs/upstream-changes.md, section 1).
    text = """
Checking configuration:
      Info: Config file not found: /etc/asterisk/rpt_extra.conf
      Info: Permission denied reading: /etc/asterisk/secret.conf
      Info: /etc/asterisk/iax.conf contains no registration lines.
      Info: /etc/asterisk/rpt_http_registrations.conf contains 2 registration line(s)
   Warning: IP test to https://conntest-west2.allstarlink.org/ip failed

Testing node 2701:
     Error: There is no apparent IAX registration attempt for node 2701

Testing node 2702:
     Error: No stats available... cannot continue this check set
   Warning: Nodeping is not responding - rate-limited or it's down

Testing node 2703:
     Error: Incoming connections to IAX from other nodes failed; client IP or firewall issue
"""
    r = authcheck.parse_text(text)
    config = r["sections"][0]["findings"]
    assert [f["data"] for f in config] == [
        {"file": "/etc/asterisk/rpt_extra.conf", "reason": "not_found"},
        {"file": "/etc/asterisk/secret.conf", "reason": "permission_denied"},
        {"file": "/etc/asterisk/iax.conf", "count": 0},
        {"file": "/etc/asterisk/rpt_http_registrations.conf", "count": 2},
    ]
    assert {f["id"] for f in config[:2]} == {"config.file_unreadable"}
    assert r["sections"][1]["findings"][0]["data"] == {"url": "https://conntest-west2.allstarlink.org/ip", "ip": None}
    n1, n2, n3 = (s["findings"] for s in r["sections"][2:])
    assert n1[0]["data"] == {"type": "IAX", "state": None}
    assert n2[0]["data"] == {"reason": "no_stats"}
    assert n2[1]["data"] == {"status": "nodeping_unavailable"}
    assert n3[0]["data"] == {"status": "unreachable"}


def test_permission_denied_is_a_run_section():
    r = authcheck.parse_text("     Error: Access denied: script must run as root or asterisk (current user: www)\n")
    assert r["result"] == "aborted"
    assert [s["id"] for s in r["sections"] if s["findings"]] == ["run"]


def test_no_nodes_aborts():
    r = authcheck.parse_text("Checking configuration:\n     Error: NO NODE ARE CONFIGURED IN rpt.conf\n"
                             "     Error: RUN asl-menu OR INSPECT THE CONFIG FILES\n")
    assert r["result"] == "aborted"


def test_http_iax_mismatch():
    r = authcheck.parse_text("   Warning: HTTP and IAX probes perceive different IPs (203.0.113.5 != 100.64.1.2); "
                             "likely behind Carrier-Grade NAT (CGNAT)\n")
    f = r["sections"][-1]["findings"][0]
    assert r["sections"][-1]["id"] == "public_ip"
    assert (f["id"], f["level"], f["data"]) == ("public_ip.http_iax_match", "warning",
                                                {"http_ip": "203.0.113.5", "iax_ip": "100.64.1.2"})
