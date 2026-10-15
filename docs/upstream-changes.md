# Upstream changes needed by asl-web-ui

asl-web-ui needs changes in two other AllStarLink packages. This file records
them in enough detail to implement later. asl-web-ui is designed on the
assumption that they will be accepted. Until they ship, asl-web-ui uses the
fallbacks described under each change.

Status: none of these changes have been started.

---

## 1. ASL3: `asl-node-auth-check --json`

Repository: `AllStarLink/ASL3`, file `bin/asl-node-auth-check` (and its man page
`bin/asl-node-auth-check.1.md`).

### Why

The web UI's Diagnostics page shows the node connectivity check as grouped,
color-coded results with fix-it hints. Parsing the current text output
(`     Error: ...` lines under `Testing node N:` headings) breaks whenever wording
changes, and it gives no stable way to attach a hint to a specific check.

### Change

Add a `--json` option. Without it, the text output stays exactly as it is now.

With `--json`, the script prints one JSON document on stdout and nothing else
(no banner, no text lines):

```json
{
  "schema": 1,
  "tool_version": "3.x.y",
  "started": "2026-10-13T18:20:41Z",
  "finished": "2026-10-13T18:21:09Z",
  "result": "error",
  "counts": { "error": 2, "warning": 0, "ok": 11, "info": 2 },
  "sections": [
    {
      "id": "config",
      "node": null,
      "complete": true,
      "findings": [
        { "id": "config.nodes", "level": "info",
          "message": "rpt.conf has configuration for: 63001",
          "data": { "nodes": ["63001"] } }
      ]
    },
    { "id": "public_ip", "node": null, "complete": true, "findings": [] },
    { "id": "node", "node": "63001", "complete": true, "findings": [] }
  ]
}
```

- `level` is one of `ok`, `info`, `warning`, `error`. These are the same four levels the text mode prints.
- `message` is the same human-readable text the text mode prints.
- `id` is a stable identifier. asl-web-ui keys its fix-it hints on it, so
  existing ids must never change meaning; add new ids instead.
- `data` holds the machine-readable values behind the message, such as addresses,
  ports, timestamps (ISO 8601 UTC) and round-trip times. Field names are listed below.
- `complete` is `false` when a section stopped early, for example after a
  registration failure.
- `result` is the worst level found, or `"aborted"` if the run could not
  continue.

### Finding ids

| id | Current text (abridged) | `data` fields |
|---|---|---|
| `config.nodes` | rpt.conf has configuration for: … | `nodes` |
| `config.no_nodes` | NO NODE ARE CONFIGURED IN rpt.conf | — |
| `config.private_node_skipped` | Skipping evaluation of private node N | `node` |
| `config.include_missing` | Include target not found | `target`, `from` |
| `config.registration_lines` | FILE contains N registration line(s) | `file`, `count` |
| `config.registration_invalid` | Invalid registration >> … << in FILE | `file`, `value` |
| `config.no_registrations` | NO VALID REGISTRATIONS EXIST … | — |
| `config.registrations` | Registrations present for configured node(s): … | `nodes` |
| `config.duplicate_registrations` | Duplicated HTTP and IAX registrations for: … | `nodes` |
| `config.missing_registration` | No registration present for configured node(s): … | `nodes` |
| `config.missing_configuration` | No configuration present for registrations for node(s): … | `nodes` |
| `public_ip.http_probe` | IP from URL reports: … / IP test to URL failed | `url`, `ip` (null on failure) |
| `public_ip.iax_probe` | IP from HOST reports: … / IP test to HOST failed | `host`, `ip` (null on failure) |
| `public_ip.http_consensus` | HTTP IP probes have / DO NOT have consensus | `ips` |
| `public_ip.iax_consensus` | IAX IP probes have / DO NOT have consensus | `ips` |
| `node.well_formed` | Node registration config is well-formed / range or host errors | `node`, `reghost` |
| `node.registration_type` | Node registration type is HTTP/IAX | `type` |
| `node.regserver_reachable` | register.allstarlink.org is (un)reachable | — |
| `node.registration_state` | HTTP/IAX registration state is … / no apparent attempt | `type`, `state` |
| `node.perceived_address` | Perceived IAX IP:PORT for this node is … | `address` |
| `node.registrar` | Registered to NAME - IP | `name`, `ip` |
| `node.udp_port` | Server-set UDP port matches / does not match bindport | `registered_port`, `bindport` |
| `node.stats_unavailable` | No stats available / stats missing fields | `reason` |
| `node.registered_recently` | Node registration within 10 minutes / not registered in last 10 minutes | `registered_at` |
| `node.ip_last_changed` | Last time IP changed was … | `changed_at` |
| `node.inbound_reachability` | Incoming connections to IAX … successful / failed / nodeping not responding / not tested | `status`, `rtt_ms` |
| `node.checks_stopped` | Stopping node checks due to registration failure | — |

### Behavior changes (both modes)

1. **Exit status.** The fatal stops currently call bare `sys.exit()`, which exits
   0. Use:
   - `0`: no errors;
   - `1`: one or more errors;
   - `2`: aborted (the run could not continue);
   - `3`: not running as root or asterisk.

   Warnings alone exit 0.
2. **"No nodes configured" never fires.** `get_rpt_nodes()` returns `[]`, never
   `None`, so the `configed_nodes is None` check in `main()` cannot trigger.
   Test for an empty list.
3. **Fatal configuration problems in JSON mode.** In JSON mode,
   duplicate/missing registrations and "no registrations" must still produce a
   complete JSON document (`result: "aborted"`, the finding included, remaining
   sections omitted). They must not exit with partial output.
4. **Wrong label.** `check_http_registration()` prints "Perceived IAX IP:PORT" for an HTTP
   registration. Label it by registration type.
5. **Permission failure in JSON mode.** `require_root_or_asterisk()` must emit a JSON document
   (`result: "aborted"`, finding id `run.permission_denied`) when `--json` is
   given.

### Also add

- `--node N`: check only node N. The configuration section still runs. asl-web-ui uses this
  to re-check a single node.
- Update the man page with `--json`, `--node`, the exit codes and the schema
  version.

### Fallback until released

asl-web-ui parses the text output into the same structure, keyed by message
patterns. It detects support with `asl-node-auth-check --help`, looking for
`--json`.

---

## 2. app_rpt: numeric "once" variants for the tuning displays

Repository: `AllStarLink/app_rpt`. Files: `channels/chan_simpleusb.c`,
`channels/chan_usbradio.c`, and possibly a shared helper in `res/res_usbradio.c`.

### Why

The web UI's native tuning page shows a live RX level meter and live
COS/CTCSS/PTT status. Today these exist only as interactive CLI loops:
`susb|radio tune menu-support b` and `… v`. Those loops redraw ASCII with `\r`
until input arrives on the console connection (`ast_radio_poll_input`).
asl-web-ui can drive them by streaming `asterisk -rx` and killing it, but it then
has to scrape bar characters to recover numbers. The drivers already use this
pattern for statistics: `y` is interactive and `Y` is "once only". The change
adds the same "once" form for the meter and the status display, with numeric
output.

### Change (both drivers, same letters and formats)

**`tune menu-support B[ms]` — one RX level sample.**
- Enable measurement the same way `tune_rxdisplay()` does: `measure_enabled`, `discfactor = 1000`, reset `amax`/`amin`.
- Wait `ms` milliseconds (default 100, clamp 20–1000).
- Restore the measurement state and print one line:

  ```
  <rxkeyed>,<apeak>,<fullscale>
  ```

  - `rxkeyed` is 0 or 1;
  - `apeak` is the raw peak, the same value `tune_rxdisplay()` uses;
  - `fullscale` is `16384`, the value the existing display scales against. The "3 kHz" and "5 kHz" marks in the TUI sit at fixed fractions of it.
- For USBRadio, read from `o->pmrChan->spsMeasure`, as its `tune_rxdisplay()` does. If there is no measure block, print `ERROR,NO_MEASURE`.

**`tune menu-support V` — status once.** Print one line:

```
<cos_mode>,<cos_active>,<ctcss_mode>,<ctcss_active>,<rxkeyed>,<txkeyed>
```

- `cos_mode` and `ctcss_mode` are 0 when detection is off (`rxcdtype`/`rxsdtype` == 0), otherwise 1.
- `cos_active`, `ctcss_active` and `rxkeyed` are 0 or 1.
- `txkeyed` is `txkeyed || txtestkey`, matching the existing `v` display.

**Calibration result lines (USBRadio `a`, `d`, `i`).**
- Context: `tune_rxinput()`, `tune_rxctcss()` and `tune_rxvoice()` print progress text only.
- Change: end each with one final line that tools can parse:

  ```
  RESULT,<name>=<value>[,<name>=<value>...]
  ```

  For example `RESULT,rxmixerset=512,rxsquelchadj=480`, or `RESULT,FAILED,<reason>`. The progress text above it is unchanged.

### Compatibility

- **Additive only.** The existing letters, including the CSV of `menu-support 0`/`0+4`, keep their exact output, as the driver comments already promise.
- **Error output:** both new commands print the existing `USB_UNASSIGNED_FMT` line when `!o->hasusb`.

### Fallback until released

asl-web-ui streams the interactive `b` and `v` loops and parses them:
- **Meter:** count the filled bar characters, out of 75 columns, to estimate `apeak`.
- **Status:** read the `Keyed`/`Clear`/`Off` fields.
- **Calibrations:** parse the existing progress text for the final setting.

It detects support by sending `B` and checking for the numeric line.

---

## 3. app_rpt: saving tune settings rewrites every included file

Repository: `AllStarLink/app_rpt`. Files: `channels/chan_simpleusb.c` and
`channels/chan_usbradio.c`, `tune_write()`, which saves with
`ast_config_text_file_save2()`.

### Observed (asl3-asterisk 3.10.8, nodes 2102 and 2104, 2026-10-15)

Saving tune settings (`menu-support j`, used by the classic tune menus and
by asl-web-ui) rewrites not only `simpleusb.conf` / `usbradio.conf` but also
every file they include: all of `custom/simpleusb/*.conf` (or
`custom/usbradio/*.conf`), which asl3-menu ships. In each rewritten file:

- the "Automatically generated configuration file" header is added or its
  date updated;
- two more blank lines are inserted after the header, on every save, so
  the customization files grow with each save;
- the main file's own formatting changes (`devstr=` becomes `devstr = `,
  keys the file did not have, such as `rxctcssadj`, `fever` and `txslimsp`,
  are added).

### Change

Write only the tune settings, in the main file: either update the existing
`key = value` lines of the device's section in place, or save with the
flags that keep included files untouched. The blank-line growth should not
happen in any case.

### What asl-web-ui does meanwhile

The tuning page shows the diff of every file the save changed, and none of
them count as "restart needed".

---

## Version-dependent behavior asl-web-ui already accounts for

**app_rpt 3.10.5** (verified 2026-10-13 against a private Asterisk instance):
- `module reload app_rpt` with an invalid `rpt.conf` logs *"Radio Repeater
  disabled"*, takes every node down, and still prints *"Module 'app_rpt'
  reloaded successfully."*
- Newer app_rpt source aborts the reload and keeps the old state.
- asl-web-ui warns before any reload or restart while `rpt.conf` has errors, on all versions.

This is already fixed upstream. It needs no change, but asl-web-ui's messages
are version-aware because of it.
