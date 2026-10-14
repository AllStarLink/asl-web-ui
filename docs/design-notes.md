# asl-web-ui design notes

Working record of the design sessions. Nothing is implemented yet: all
decisions come before any code. Last updated 2026-10-14 (session 2).

- Clickable mockup (private): https://claude.ai/artifact/38FoRhoem3VfmuXvcbhEVD
  (version 6). Source is in [mockup/](mockup/); see "Mockup" at the end.
- Upstream changes needed in ASL3 and app_rpt: [upstream-changes.md](upstream-changes.md).

## Where we left off

Every design topic is decided (sections 9, 12, 13 and 14 on 2026-10-14). The
consolidated design document, [DESIGN.md](DESIGN.md), is awaiting the user's
approval. This file remains the working log.

Design topics still ahead, in the agreed order:

1. ~~Config engine.~~ Decided (section 9).
2. ~~Backend architecture.~~ Decided (section 12).
3. ~~Packaging layout.~~ Decided (section 13).
4. ~~Testing strategy.~~ Decided (section 14).
5. Then a consolidated design document for approval, before any implementation.

---

## 1. Goal and scope

- A complete web UI for AllStarLink. **Phase 1:** everything asl3-menu does
  (`~/code/asl/asl3-menu`: `asl-menu`, `node-setup`, `asl-backup-menu`).
- **Future modules**, with room left for them now:
  - full Allmon3 management (config and users);
  - scheduled tasks (app_rpt scheduler, cron, or systemd timers; still to be analyzed);
  - sound-file upload for playback.
- A companion to Allmon3, with deeper integration later.
- **Name:** `asl-web-ui` everywhere: the package, the URL `/asl-web-ui/`, the login group,
  units, the PAM service and paths. The repo directory is `asl3-web-ui`; the
  difference is deliberate.
- **License:** AGPL-3.0.
- **AI use:** follow ASL003. Commits carry an `Assisted-by:` trailer, never
  Co-Authored-By. AGENTS.md and CLAUDE.md are copied from asl3-menu.

## 2. Stack

- **Backend:** Python, **aiohttp + aiohttp-session**, matching Allmon3. It runs as a
  systemd service as user **asterisk** and listens on a **Unix socket**.
- **Frontend:** **React + PatternFly 6 + TypeScript**, bundled with esbuild, looking as
  close to Cockpit as reasonable. All logic lives in the backend; the frontend stays thin.
- **Editor:** **CodeMirror 6**, also used for diff/merge views. **xterm.js** for the
  Asterisk console and the classic tune menu.
- **Node at build time only:** a **pinned upstream Node LTS tarball (SHA-256 verified)
  installed in `builder/Dockerfile`**. `dockerbuild.sh` runs on the host, so Node
  doesn't go there.
  - `make deb` runs `make frontend` (`npm ci --ignore-scripts` + esbuild) first.
  - dpkg-buildpackage itself needs no Node.
  - The package is `Architecture: all`.
- **Debian:** trixie, and plan for Debian 14 (forky). Bookworm is dropped.
- **Apache:** a `conf-available` snippet enabled by postinst, as Allmon3 does, with
  WebSocket proxying. Apache provides TLS; the app never changes vhosts.

## 3. Authentication and sessions

- **PAM authentication:** a **socket-activated root helper** (systemd `Accept=yes`,
  socket mode 0600 owned by asterisk), written in Python.
  - It runs the **full PAM conversation**, so MFA such as pam_google_authenticator works
    by PAM configuration alone.
  - It uses a ctypes PAM binding. python3-pamela is a candidate.
  - PAM service: `/etc/pam.d/asl-web-ui`.
- **Who can log in:** members of the dedicated Unix group **`asl-web-ui`**, created by
  postinst. Membership is re-checked on every request. Root is blocked by default.
- **Sessions:** server-side, in memory. A restart of the daemon logs everyone out.
  - **"Keep me signed in"** (checked): 30-day absolute limit, 7-day idle limit.
  - Unchecked: 8 hours, 30-minute idle limit.
  - Cookies are HttpOnly, SameSite=Strict, and Secure.
  - A CSRF token is bound to the session and sent as a header.
  - Login backoff per IP and per user (IP from X-Forwarded-For, trusted only because
    of the Unix socket); failed logins logged in a fail2ban-friendly format.
- **HTTPS is required by default.** A documented `allow_insecure_http` option exists.
  Over HTTP the login page explains why it refuses.
- **Recent-authentication window (10 minutes)** for destructive actions: reboot,
  shutdown, restore, factory reset, node removal, stopping Asterisk, AMI secret change,
  fixing permissions.

## 4. Privilege model

- **systemctl** for asterisk / allmon3 / asl3-update-nodelist, and reboot/poweroff
  through logind. Each is allowed by a **polkit rule limited to the asterisk user and
  to those unit names**.
- **One privileged helper, `asl-web-ui-priv`** (revised 2026-10-14, B1). It is a
  **socket-activated root service**, not pkexec, and authorizes every request with
  **polkit** via `pkcheck --process pid,start,uid` (from `polkitd`; not setuid). No
  setuid binary is involved, so the web service can run with `NoNewPrivileges=yes`.
  It has a fixed list of commands and strict argument validation (details in
  section 12):
  - backup create and restore;
  - backup include list;
  - factory restore;
  - `allmon3.ini` edits;
  - fixing file ownership under /etc/asterisk.
- **Root-owned files in /etc/asterisk** (for example after `sudo vim`): detected and
  shown, with a **Fix permissions** button (chown to the owner of /etc/asterisk).
- **Restore safety (asl-backup-menu is not a model):**
  - only paths in the include list are extracted;
  - absolute paths, `..`, and links pointing outside those paths are rejected;
  - a snapshot is taken before restoring.

## 5. Asterisk integration

- Use the **control socket (`asterisk -rx`)**, not AMI. AMI lacks hooks needed here,
  and its credentials are a setting the UI itself edits.
- **"Restart pending"** is computed: any config file modified after Asterisk started.
  It's shown as a Cockpit-style banner plus a top-bar indicator.
- **Check before restart and reload.** If rpt.conf has errors, every restart path
  *and* the Asterisk console (before `module reload [app_rpt]`, `core reload`,
  `rpt restart`, `core restart now|gracefully|when convenient`) warn, with
  **Fix in editor** as the main action and **Run anyway** as a secondary one.
- **Write safety:** flock, a hash check against the version the edit was based on,
  a snapshot (`/var/lib/asl-web-ui/snapshots`), and an atomic rename that preserves
  owner and mode. Multi-file changes show a combined diff and are applied
  all-or-nothing.

## 6. Screens

Approved structure. The mockup implements all of it.

- **Overview:** health, nodes, Asterisk, and system cards (Reboot and Shut down are
  here, as in Cockpit), plus a first-run empty state.
- **Nodes:** a table, and an **Add node** wizard:
  1. number;
  2. password;
  3. configuration preset (manual, common, or device from `;MENU:` tags);
  4. interface;
  5. callsign;
  6. customizations;
  7. review the diff.

  The Manual preset still asks for interface and callsign. The node detail page has
  tabs: **General, Radio interface, Tuning, Access control, Customizations**.
- **Asterisk:** Status (service, registrations) · Settings (AMI secret, which also
  syncs Allmon3; IAX port) · Console (Asterisk CLI only).
- **Manual Config Edit** under an "Advanced / Expert" heading, deliberately
  discouraging. It lists the 11 files with owner and lint status and opens them in
  the CodeMirror editor.
- **Diagnostics:** the node connectivity check (`asl-node-auth-check`) plus basic
  checks (ping, Asterisk version, node-list service with a restart button).
- **Backups:** This server · AllStarLink cloud · Settings (include list, factory reset
  in a danger zone).
- **Dropped from asl3-menu:**
  - root bash shell;
  - "ASL menu at login" toggle;
  - web-exposed `--post-exec`;
  - info screens (replaced by inline help).
- **Added beyond asl3-menu:** Upload backup. It can be dropped.
- The backend is organized as **feature modules**, each registering routes,
  navigation entries and privileged commands, so Allmon3, scheduling and sounds can be
  added later.

## 7. Diagnostics

- **`asl-node-auth-check`** (ASL3) runs as asterisk; no privilege is needed.
  - It runs **only on demand**, because it takes about 30 seconds and calls
    rate-limited services. The last result is cached and shown on the Overview.
  - It replaces asl-menu's "check registration server" and "show registrations".
  - The web UI uses its proposed `--json` mode; see upstream-changes.md.

## 8. Config validation (lint): agreed principle

- **Error:** only when it can be demonstrated in the Asterisk or app_rpt source
  **and** confirmed by a conformance test against real Asterisk. Today that means:
  - Asterisk rejects the whole file (config.c `process_text_line` returns −1 →
    `CONFIG_STATUS_FILEINVALID`): a missing `]` or `)`, inheriting from an undefined
    or later-defined template, or `(+)` on a missing category;
  - or a configured node cannot come up.
- **Warning:** the file loads, but something is ignored or overridden: a line with
  no `=`, a duplicate key within the stanza itself, an unknown directive, and so on.
- **Info:** valid but unusual.
- **Status in Manual Config Edit,** most severe first: owned by root → N errors →
  N warnings → OK.
- **Saving a file with errors** asks for confirmation; it isn't blocked.
- **Division of labor:** static config problems belong to the lint; live network
  state belongs to asl-node-auth-check.

### Verified facts (private unprivileged Asterisk instance, installed asl3 3.10.5)

- **ASL patches Asterisk's config parser.** Patches live in
  `asl3-asterisk/debian/patches/config_c_*.patch`, listed per release in `series.v22.x`.
  Active in 22.8+: template_inheritance_overrides (ASTERISK-30370),
  template_writing, ast_variable_update, deep_wide_templates.
  `~/code/asl/asl3/asterisk` is **unpatched upstream** and must not be used as the
  reference.
- **The last value wins,** both for template overrides and for plain duplicate keys.
- **An undefined template in rpt.conf** takes every node down. On 3.10.5 even
  `module reload app_rpt` does it, while the CLI reports "reloaded successfully".
  A restart does it too. Newer app_rpt source aborts the reload and keeps the old
  state instead.
- **Test-instance recipe:** see [research/asterisk-test-instance/](research/asterisk-test-instance/).
  - Replace `@TESTDIR@`.
  - `astrundir` must be short, for example `/run/user/1000/...`, because the socket
    path is limited to 108 characters.
  - app_rpt needs res_curl, bridge_softmix and chan_bridge_media.
  - Observe which rxchannel was used with `core show channels concise` and USRP
    channels.

## 9. Config engine (DECIDED 2026-10-14)

### 9.1 Two layers

- **Lossless file model.**
  - Typed lines, each keeping its exact original bytes.
  - Only changed lines are regenerated.
  - Parse then write with no edits is byte-identical, tested on the corpus.
  - New lines copy the style of their neighbors.
- **Asterisk's view of the files,** reproducing ASL-patched Asterisk:
  - includes expanded as text; `#tryinclude` globs may match nothing; a missing
    `#include` is an error;
  - templates copied when the header is read, and they must be defined first;
  - the last value wins; repeatable keys keep every occurrence;
  - every effective value records its origin (file, line, inherited or not).
- **Checked by the conformance suite:** the test instance prints
  `AST_CONFIG(file,cat,key,-1)` for every key, and the result must match the engine's.

### 9.2 Intents

The guided pages express intents; the planner turns each into the smallest change:

- `set` / `unset`;
- `add_category` / `remove_category` / `rename_category` / `set_templates`;
- `add_value` / `remove_value` (repeatable keys);
- `comment` / `uncomment`;
- `set_module`.

`set` replaces the stanza's own line in place, or inserts an override line if the value
only comes from a template. **Edits go to the file where the definition lives.**
**Guided pages never edit templates or the package's `custom/` files.**

### 9.3 Requirements per operation

Each operation declares what must be true. If that fails, only that operation is
disabled, with the reason and a link to the line. `#exec` output can't be modeled.

### 9.4 Applying changes

lock → hash check → snapshot → write temp files, sync, rename → restore from the
snapshot if a later rename fails.

### 9.5 Other file formats

`savenode.conf` (shell KEY=VALUE) and `allmon3.ini` (INI, edited through the
privileged helper) get lossless models of their own.

### 9.6 Decisions (all recommendations accepted 2026-10-14)

- **D1. A key appears twice in the stanza.** [Update the line that's in effect. The
  preview offers an unchecked option to remove the redundant earlier one.]
- **D2. Callsign change when idrecording isn't `|iCALL`.** [Don't overwrite silently;
  show it and offer to replace.]
- **D3. AMI secret.** [Change only the `[admin]` user (Allmon3's); list other AMI users
  and leave them alone. node-setup's sed changes every matching secret.]
- **D4. "Enable customizations".** [Run asl3-menu's update-configuration-files.py with
  `--dir-in/--dir-out` on a temporary copy, then diff, preview, and apply through the
  transaction.]
- **D5. Removing a node: comments above its stanza.** [Keep them, unless they mention
  the node number; then show them in the preview as removed, with an option to keep.]
- **D6. Interface change: the old channel section** (for example `[N]` in
  simpleusb.conf). [Keep it, as node-setup does, and say so in the preview.]

## 10. Interface tuning (decided)

- **Native web UI** driving `susb|radio tune menu-support <letter>[value]`.
  - **Settings:** read from the stable CSV form (`menu-support 0`/`0+4`).
  - **Live meter and status:** stream-parse the interactive `b`/`v` loops now. They
    are loops inside Asterisk that end when the console connection gets input or
    closes, so the backend streams `asterisk -rx` and kills it to stop.
  - **Upstream:** numeric "once" variants `B` and `V`, plus USBRadio calibration
    `RESULT` lines (upstream-changes.md).
- **Save** calls the driver's own save (`j`), with a snapshot first, a "what changed"
  diff afterwards, and **Undo**.
- **One tuning session per driver,** because the driver has a single global "active
  device". The UI also detects a TUI running over SSH (by process name) and warns.
- **Test tone:** explicit start, auto-stop timeout, a prominent indicator, and a stop
  when the page is left or the connection drops.
- **USBRadio calibrations** (noise, CTCSS, voice) are guided steps that state the
  signal required first.
- **"Open classic tune menu"** fallback: an xterm running only the tune menu, as
  asterisk, not a shell.
- **Testing needs real hardware.** The user will provide an instance once there is
  testable code.

## 11. Development environment facts

- **Dev box:** WSL Debian 13 with systemd running. asl3 3.10.5 is installed.
  `/etc/asterisk` and the system Asterisk are **fungible**, so they can be used and
  modified for testing. Passwordless `sudo -n` works.
- **Committed fixtures** use placeholder secrets (ASL003). The stock config snapshot
  can be regenerated from `/etc/asterisk` or the asl3-asterisk-config .deb.

## 12. Backend architecture (DECIDED 2026-10-14)

### Processes

| Unit | Runs as | Purpose |
|---|---|---|
| `asl-web-ui.service` | asterisk | The aiohttp app on `/run/asl-web-ui/web.sock` (0660, group www-data), sandboxed with `NoNewPrivileges=yes`. |
| `asl-web-ui-auth.socket` / `@.service` | root, one process per login | PAM conversation and group check only. The socket is reachable only by asterisk. |
| `asl-web-ui-priv.socket` / `@.service` | root, one process per request | Privileged commands. `SO_PEERCRED` → `pkcheck --action-id org.allstarlink.asl-web-ui.<command>`. The shipped rule grants the actions to the asterisk user; admins may tighten it. The web username is passed for audit only. |

### Privileged commands (phase 1)

- `backup.create`, `backup.restore(name)`, `backup.delete(name)`
- `backup.import(staged_name)`
- `backup.write_include_list(content, expected_hash)`
- `factory.restore` (streams output)
- `file.write(path, content, expected_hash)`: allowlisted paths only; phase 1 is
  `/etc/allmon3/allmon3.ini`
- `asterisk.fix_ownership(path)`: the real path must be a regular file under
  /etc/asterisk

Service control and power actions use systemctl plus polkit rules, not this helper.

### Auth helper protocol

Newline-delimited JSON, one login per connection:
`start{user,rhost}` → `prompt{echo,text}` / `answer{value}` … → `result{ok,user|reason}`.

- `pam_authenticate`, then `pam_acct_mgmt`; `PAM_RHOST` is set; then the group check.
- The browser only ever sees "login failed". Reasons go to the journal.
- 120-second limit; passwords are never logged.

### Decisions

- **B2. No PAM session is opened.** Expired passwords get "change it over SSH" in
  phase 1.
- **B3. Asterisk access** is `asterisk -rx` subprocesses with a concurrency limit,
  using a pseudo-terminal for interactive streams. The native console protocol is
  not used.
- **B4. API:**
  - REST/JSON under `/asl-web-ui/api/v1/`;
  - one multiplexed WebSocket per browser session (jobs, restart-pending, live
    status, tuning);
  - one WebSocket per terminal;
  - long-running operations are jobs.
- **B5. Every change uses plan/apply.** `POST /changes/plan` (intents) returns a
  `plan_id`, diffs, warnings and requirement failures; `POST /changes/{id}/apply`
  applies it. Plans are tied to the session and file hashes and expire after
  5 minutes.
- **B6. Audit:** `/var/lib/asl-web-ui/audit.jsonl` (who, what, files, snapshot,
  result), also sent to journald with structured fields.
- **B7. One shared background poller** (5–10 seconds, only while a client is
  connected) for status, pushed to every client.

### Feature modules

Each module registers routes, navigation entries (`/api/v1/manifest`), the
privileged commands it relies on, and background tasks.

Phase 1 modules: `core`, `system`, `asterisk`, `nodes`, `tuning`, `config_files`,
`diagnostics`, `backups`.

### Paths

- `/etc/asl-web-ui/asl-web-ui.ini`: the UI's own settings
- `/var/lib/asl-web-ui/`: snapshots, cached connectivity check, audit log
- `/usr/share/asl-web-ui/www/`: the built frontend, served by Apache

## 13. Packaging (DECIDED 2026-10-14)

Follows the asl3-menu and Allmon3 conventions: a top-level Makefile with
`RELVER`/`DEBVER`, `install`, `deb`, `debprep`, `debclean` and `verset`; `dh` with a
simple `debian/rules`; pandoc-built man pages.

### Repo layout

- `backend/`
  - `asl_web_ui/`: the web app (`core/`, `configengine/`, `modules/…`)
  - `asl_web_ui_auth/`: root helper, stdlib + PAM ctypes only
  - `asl_web_ui_priv/`: root helper, stdlib only
  - `bin/`, `tests/`, `Makefile`
- `frontend/`: `package.json`, the lockfile, `src/`; `dist/` is git-ignored
- `conf/`: the ini, the Apache snippet, `pam.d/`, `polkit/`
- `doc/`: man pages
- `tests/conformance/`
- `debian/`
- `builder/`: Dockerfile with pinned Node, `dockerbuild.sh`, `entrypoint.sh`
- `.github/workflows/`: from the asl3-workflows template
- `docs/`

### Decisions

- **P1. Python location:** a private directory, `/usr/share/asl-web-ui/python/`, per
  Debian's Python policy. (Allmon3 uses dist-packages.)
- **P2. Root helpers:** in `/usr/libexec/asl-web-ui/`. Each imports only its own
  package and the stdlib, never the web app.
- **P3. systemd units:** in `debian/`, installed by `dh_installsystemd`; the service
  and both sockets are enabled and started. The main service is hardened
  (`NoNewPrivileges`, `ProtectSystem=strict` with `/etc/asterisk` and
  `/var/lib/asl-web-ui` writable, `PrivateTmp`, `ProtectHome`, …). Each option is
  verified during implementation.
- **P4. Apache snippet:**
  - `Alias /asl-web-ui` → the built frontend;
  - `ProxyPass /asl-web-ui/api` → the Unix socket, with WebSocket upgrade;
  - CSP, `X-Frame-Options DENY`, `Referrer-Policy`, `nosniff`.

  postinst enables `proxy`, `proxy_http`, `proxy_wstunnel`, `headers` and the conf
  via `apache2_invoke`. It never touches vhosts or SSL. HSTS is documented for the
  admin's TLS vhost.
- **P5. First login:** postinst creates the `asl-web-ui` group and
  `/var/lib/asl-web-ui` (asterisk, 0750). It adds no users. It prints
  `usermod -aG asl-web-ui <user>`, and the login page explains when the group is
  empty.
- **P6. Dependencies:**
  - Depends: `python3 (>= 3.13)`, `python3-aiohttp`, `python3-aiohttp-session`,
    `apache2`, `polkitd`, `asl3-asterisk`, `asl3-menu` (for
    update-configuration-files.py, D4), `adduser`.
  - Recommends: `allmon3`.
- **P7. Conffiles:** the ini, the Apache snippet, the PAM file. The polkit rule is
  in `/usr/share/polkit-1/rules.d`; admins override it in `/etc/polkit-1/rules.d`.
- **P8. Versioning:** `RELVER`/`DEBVER` + `@@HEAD-DEVELOP@@` via `make verset`, as
  Allmon3 does. The frontend gets the same version.
- **P9. Frontend:** `dist/` is not committed. `make deb` runs `make frontend`; the
  result installs to `/usr/share/asl-web-ui/www/`.
- **P10. Man pages:** pandoc from Markdown: `asl-web-ui(8)` and one for the config
  file.
- **P11. CI:** the asl3-workflows `make_and_publish_pkgs.yml` template. Trixie now;
  forky when ASL builds for it. One build per Debian release (`Architecture: all`).
- **P12. Lintian** runs in CI; warnings don't fail the build at first.

## 14. Testing strategy (DECIDED 2026-10-14)

Tools come from trixie: pytest 8.3, hypothesis 6.130, pytest-aiohttp, pytest-cov,
flake8, black, mypy, pylint. ruff is not packaged in trixie.

- **T1. Unit tests (pytest):** config engine, lint rules, validation, sessions,
  CSRF, rate limiting, the auth helper protocol (fake PAM), the privileged helper's
  command table (fake pkcheck), and the API through the aiohttp test client.
- **T2. Corpus + property-based tests:**
  - stock configs per ASL release (from the asl3-asterisk-config debs) plus curated
    hand-messed variants, with placeholder secrets;
  - byte-identical round trip;
  - hypothesis-generated files check that intents touch only the intended lines.
- **T3. Parity with node-setup:**
  - load node-setup's shell functions with `whiptail` stubbed and `CONFIG_DIR`
    pointing at a temporary copy (node-setup honors `CONFIG_DIR`), run each
    `do_node_*` operation, and run the same operation through the engine;
  - assert they're equivalent as Asterisk sees them (effective values), not
    byte-identical;
  - expected differences (D2, D3) are recorded explicitly.
- **T4. Conformance against real Asterisk:**
  - uses the private unprivileged instance;
  - effective values must match `AST_CONFIG(...,-1)` for every key;
  - each error rule's fixture must produce the "disabled" outcome, and each warning
    fixture must load;
  - runs locally, and in CI in a trixie container with ASL packages from the ASL
    apt repo, once per supported ASL release.
- **T5. Security:**
  - malicious restore archives (`..`, absolute paths, links outside the backup
    paths, device files, oversized members);
  - hypothesis fuzzing of the privileged helper's arguments;
  - polkit refusals and socket permissions enforced;
  - the auth helper never logs secrets and gives up after its time limit.
- **T6. Frontend:**
  - `tsc` and ESLint; Vitest with Testing Library;
  - **Playwright** end-to-end (login including a second PAM prompt, add-node wizard,
    rename with diff, restart check, Manual Config Edit save) against the real
    backend and the private Asterisk in CI, with axe-core accessibility checks;
  - versions come from the pinned Node lockfile.
- **T7. Package tests:**
  - CI: install into a clean trixie container, check files, permissions, conffiles
    and group, upgrade from the previous version, purge; lintian;
  - each release: a full systemd + Apache + polkit test on a VM or the user's
    instance.
- **T8. Tuning:**
  - a recorded-transcript fake of `menu-support`, captured on real hardware, for the
    parsers and the page in CI;
  - a manual checklist on real hardware before each release.
- **T9. Quality gates:**
  - black, flake8, mypy (strict on `configengine` and both helpers);
  - coverage reported, with a minimum only on the engine and the helpers;
  - frontend ESLint and `tsc`.
- **T10. Local development mode:** `asl-web-ui --dev` serves the esbuild watch
  output with a **fake login backend** and talks to the private test Asterisk.
  - It refuses to start when running from `/usr/share/asl-web-ui` or as `asterisk`.
  - A packaged install can never enable it.

## Mockup

[mockup/](mockup/) holds the source of the published mockup. To rebuild:

1. Download into one directory, from jsDelivr: `@patternfly/patternfly@6.6.0`
   `patternfly.min.css`, `assets/fonts/webfonts/fa-solid-900.woff2`, and the
   RedHatText, RedHatDisplay and RedHatMono `*VF.woff2` fonts.
2. Run `python3 -I build.py <that-dir> <out.html>`.

`smoke-test.js` loads the script with a stub DOM and renders every page:
`node smoke-test.js mockup.js`.

The mockup is a design tool, not product code.
