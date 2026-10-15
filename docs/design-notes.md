# asl-web-ui design notes

Working record of the design sessions. Nothing is implemented yet: all
decisions come before any code. Last updated 2026-10-14 (session 2).

- Clickable mockup (private): https://claude.ai/artifact/38FoRhoem3VfmuXvcbhEVD
  (version 6). Source is in [mockup/](mockup/); see "Mockup" at the end.
- Upstream changes needed in ASL3 and app_rpt: [upstream-changes.md](upstream-changes.md).

## Where we left off

**M0 (skeleton), M1 (login and shell), M2 (Manual Config Edit), M3 (nodes), M4 (privileged helper, backups) and M5 (diagnostics) are complete** on `main`. Next is M6 (tuning).

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

## 15. Implementation decisions during M0 (2026-10-14)

- **nginx is supported as well as Apache** (user decision).
  - The package ships `/etc/asl-web-ui/nginx.conf`, to be included inside the
    admin's `server { }` block, following Allmon3's pattern. postinst prints the
    `include` line when nginx is installed.
  - Depends: `apache2 | nginx`.
  - Both servers must be tested.
- **WebSocket endpoints live under `/api/v1/ws/`.** nginx needs per-location
  upgrade headers, and a `map` cannot go in an include. Apache uses
  `ProxyPass … upgrade=websocket`, so `proxy_wstunnel` is not needed.
- **Client IP:** Apache's mod_proxy *appends* to a client-supplied
  `X-Forwarded-For`, and the nginx snippet *replaces* it. The backend must use
  only the **last** entry.
- **The API socket comes from `asl-web-ui.socket`** (asterisk:www-data 0660), via
  systemd socket activation. The socket is enabled on install; the service starts
  on demand.
- **`/var/lib/asl-web-ui`** is created by `StateDirectory=` (asterisk, 0750), not by
  postinst.
- **The version string** is substituted at install time (`RELVER`), not by editing
  source files in place. `make deb` restores `debian/changelog` after `debchange`
  without needing git.
- **Local builds:** `builder/localbuild.sh` (`make podman-deb`) builds only, with
  Podman. `builder/dockerbuild.sh` stays the CI build-and-publish script, with an
  engine override.
- **Pinned toolchain:**
  - Node 24.21.0 (published SHA-256 for x64 and arm64; Node 24 has no armv7l
    build);
  - npm 11.19.0;
  - the lockfile is generated with `npm install --before=2026-09-30`, so the
    two-week rule covers transitive dependencies too (`make -C frontend lock`);
  - React 19.3.0, PatternFly 6.6.2, esbuild 0.28.2, TypeScript 7.0.2.
- **Tests run during the package build** (`dh_auto_test` → `make check`), so pytest
  is a Build-Depends.
- **Dev box:**
  - Apache runs on 8080/8443, because the user's nginx owns 80/443 (approved);
  - nginx is tested with a temporary private nginx process that includes the
    packaged snippet, never by editing the system nginx;
  - test builds are installed with `dpkg -i` or `--no-install-recommends`.

## 16. Implementation decisions during M1 (2026-10-14)

- **Auth helper** (`backend/asl_web_ui_auth/`): ctypes binding to libpam
  (pam_start, PAM_RHOST, pam_authenticate, pam_acct_mgmt), with a conversation
  callback relayed over JSON lines.
  - **Result reasons:**
    - `denied` covers every failure before the password is known to be good, so
      an unknown user looks exactly like a wrong password;
    - `not_permitted` (not in the group) and `expired` are only sent after PAM
      accepted the credentials;
    - root is refused before PAM runs.
  - **Verified against real PAM** in a container and on the dev box.
  - **Hardening is lighter than the main service, on purpose:**
    pam_google_authenticator writes in the user's home directory (so no
    `ProtectHome`/`ProtectSystem`), pam_faillock writes under `/run`, and the
    libffi callback needs executable memory (so no `MemoryDenyWriteExecute`).
- **CSP allows inline styles** (user decision): `style-src 'self'
  'unsafe-inline'`.
  - xterm.js injects `<style>` elements computed at run time and supports no
    nonce, so the console text was invisible under the strict policy.
  - Scripts remain `'self'` only.
  - Login and Overview had no violations, so only the console needed this.
- **nginx forwards `Host $http_host`**, not `$host`: `$host` drops the port, which
  broke the origin check.
- **Systemd units live in `conf/systemd/`** and are installed by the Makefile;
  `dh_installsystemd` only enables and starts the two sockets. (dh only picks up
  extra unit files under its `debian/<pkg>.<name>.<unit>` naming.)
- **Live status:** the events WebSocket does *not* count as activity for the
  idle timeout. Each push re-checks the session and group, and the socket closes
  with code 4401 when the session ends.
- **Asterisk console:**
  - runs `asterisk -rvvv` on a pseudo-terminal, as the asterisk user, with at most
    3 per user;
  - a streaming filter drops only the `-- Remote UNIX connection [disconnected]`
    announcements caused by our own poller, handling lines split across reads
    and incomplete escape sequences.
- **Deferred to M2**, because both need the include-aware config engine:
  - the console's warning before reload commands;
  - the "restart pending" banner.
- **aiohttp 3.11 (trixie) has no `web.RequestKey`**; request-scoped values use a
  string key.
- **Dev mode** (`asl-web-ui-server --dev`):
  - serves the UI at `/` (`url_prefix ""`);
  - logs in with dev/dev and skips the Unix group check;
  - `--asterisk-conf` points it at a private Asterisk from
    `tests/asterisk/instance.sh`.
- **Test tooling added:**
  - `tests/e2e/smoke.py`: end-to-end check through a real web server with a
    real account;
  - `tests/e2e/screenshot.py`: headless Firefox over WebDriver BiDi, printing
    browser console and CSP errors;
  - `tests/asterisk/instance.sh`: start/stop/cli for a private Asterisk.
- **Dev box:**
  - kept test account `aslwebtest` (in `asl-web-ui`; password in
    `~/.local/share/asl-web-ui-test/aslwebtest.password`, mode 0600, never in
    the repo);
  - Apache default-ssl enabled on 8443 with the snakeoil certificate;
  - nginx tested via a private TLS instance on 8091.

## 17. Implementation decisions during M2 (2026-10-14)

- **Config engine** (`backend/asl_web_ui/configengine/`):
  - `text.py` is a line-preserving lexer whose comment handling is a port of
    `strip_comments` in main/config.c (`;` comments, `\;` escapes, nested
    `;-- --;` blocks, a stray `--;` ending the file for Asterisk). Untouched
    lines round-trip byte for byte (property-tested with hypothesis).
  - `model.py` resolves `#include`/`#tryinclude`, templates and `(+)` the way
    the ASL-patched Asterisk does.
  - `lint.py`: *error* = Asterisk rejects the file (shown in config.c and by a
    conformance test); *warning* = something is ignored or overridden;
    *info* = everything else.
  - `store.py`: plan/apply. Plans are bound to the session, single use, and
    expire after 5 minutes. Apply takes a `flock`, re-checks the hash, keeps a
    snapshot with a manifest under `state_dir/snapshots`, writes temp file +
    fsync + `os.replace` keeping owner and mode, rolls back on failure, and
    appends to `audit.jsonl`.
- **Semantics verified by `tests/conformance/`** (24 tests, private Asterisk,
  `AST_CONFIG` in a generated dialplan run through `channel originate`):
  - last value wins (the ASTERISK-30370 patch);
  - templates are copied when the header is read, so they must come first;
    they are invisible to lookups, and `(+)` cannot extend one;
  - section names match case-insensitively;
  - `+=` appends the raw text after `=`, including the leading space;
  - an included file starts in the includer's current section, and the
    includer continues in its own section afterwards;
  - a missing `#include`, or a variable before any section, rejects the file;
    a missing `#tryinclude` does not.
  - The harness needs `app_verbose` and `res_clioriginate` in the test
    instance's modules.conf.
- **API** (`modules/config_files.py`): a fixed list of 11 files; list, read,
  `check` (lint a draft), `plan`, and `changes/{id}/apply` with
  `confirm_errors`. CRLF line endings are kept. Files that are not UTF-8 are
  shown read-only. Files the asterisk user cannot write return a
  `sudo chown` hint; the Fix permissions button waits for the privileged
  helper (M4).
- **Restart pending** (`restart.py`): any `*.conf` under the config directory
  whose mtime is later than Asterisk's start (now − uptime), except
  `savenode.conf`. It is computed from the files, so hand edits and asl3-menu
  count too. rpt.conf lint results are cached by mtime and size of rpt.conf and
  everything it includes. Status carries `config.changed`, `config.rpt_errors`
  and `config.rpt_first_error`.
- **Frontend:**
  - "Manual Config Edit" sits under a separate *Advanced* heading at the bottom
    of the navigation, with an *Expert* badge, and opens with a danger notice.
  - Editor: CodeMirror 6 with a small StreamLanguage for Asterisk syntax, a
    lint gutter fed by the `check` endpoint (700 ms debounce), Revert and
    Download. Save shows the diff and the findings; with errors the only
    button is a red "Save anyway".
  - The restart-pending banner sits above every page; it is informational
    until the restart action arrives (M3) and turns red, with a link to
    rpt.conf, when rpt.conf has errors.
  - Console: the page tracks what is typed on the current line. On Enter for
    `module reload [app_rpt[.so]]`, `core reload`, `rpt restart` or
    `core restart now|gracefully|when convenient` while rpt.conf has errors,
    Enter is held and a dialog offers Fix in editor / Run anyway / Cancel
    (Cancel clears the line with Ctrl-U). After history recall, completion or
    cursor keys the line is unknown and nothing is intercepted, which is
    deliberately best-effort; the banner still shows the problem.
- **Verified:** the hardened service can save `/etc/asterisk/rpt.conf` and
  write snapshots in `/var/lib/asl-web-ui` (a save-and-restore through the
  installed package keeps owner, mode and contents). Smoke test extended with
  read-only config checks, passing through Apache and nginx.
- `tests/e2e/screenshot.py --before JS` (repeatable) runs scripts before the
  clicks; the CodeMirror view is reachable as
  `document.querySelector(".cm-content").cmTile.root.view`.

## 18. Implementation decisions during M3 (2026-10-15)

- **Edit layer** (`configengine/edit.py`):
  - A `Workspace` holds working copies of the files; the Asterisk model
    reads them, so each step of a multi-step change sees the previous ones.
    `changes()` gives the plan.
  - `Section.set` changes the line Asterisk uses (D1), in whichever file it
    lives; a value that only comes from a template gets an override line in
    the section (after its last variable, copying the neighbours' spacing).
    Templates are never edited. A later `+=` is handled by adding a plain
    line after it. `;` in values is escaped.
  - `remove_section` keeps trailing comments (they usually introduce the
    next section) unless they mention the node (D5).
  - `set_module` switches `load`/`noload` in place, keeping columns, and
    adds a `load` line when needed (stock modules.conf has `autoload = no`).
- **Node planner** (`nodes/planner.py`, `nodes/customize.py`): one method per
  node-setup operation, reading effective values (`nodes/info.py`) instead of
  grep. `savenode.conf` (shell syntax) has its own tiny model.
- **Parity tests** (`tests/parity`, 54 tests): node-setup's own functions run
  on a copy of the stock files (asl3-asterisk-config and asl3-menu, fetched
  with `apt-get download` in the installed versions and cached in
  `~/.cache/asl-web-ui-tests`; not vendored, they are GPL-2). Dialog answers
  come from a queue kept in a file, because whiptail runs in `$(...)`
  subshells. The comparison is what Asterisk would load: the last value per
  key, every value for repeatable keys, plus the channel drivers' load state.
- **Intended differences from node-setup**, asserted by the tests:
  - **D7.** node-setup's noload pattern (`load =>`) does not match the stock
    modules.conf (`load    =`), so it never unloads a driver. Here unused
    channel drivers are set to noload.
  - **D8.** Going from duplex 1 to 0, node-setup adds `hangtime = 100` and
    then deletes it again (its second block removes the 400 case's line).
    Here the node ends with hangtime 100, as intended.
  - **D9.** Renaming a node also renames its `[events-N]` (etc.) stanzas and
    the node's references to them; node-setup leaves them under the old number.
  - **D10.** Adding a node uses the new node's own (template) values for the
    duplex/hangtime rules; node-setup uses whatever node was viewed last.
  - The rest matches, including first run (rename 1999, the stock
    registration placeholders becoming the new node's), device presets and
    customizations.
- **API** (`modules/nodes.py`): `POST /api/v1/nodes/plan {op, ...}` returns
  every file's diff, notes, new lint errors and manual Allmon3 steps; applying
  goes through the shared `modules/changes.py`, whose plans can carry
  follow-up steps (AstDB list moves on rename) and require a recent password
  (node removal). Unwritable files are reported with a `sudo chown` hint.
- **Access lists** go straight to AstDB with `database put/del/deltree` (no
  plan, no restart), logged in the audit log.
- **Asterisk control** (`modules/control.py`): restart/start/stop and
  reboot/poweroff via `systemctl --no-ask-password`, allowed by
  `/usr/share/polkit-1/rules.d/50-asl-web-ui.rules` for the asterisk user only
  (asterisk, allmon3, asl3-update-nodelist units; login1 reboot/power-off).
  Verified: the rule allows restarting asterisk.service and refuses other
  units. Start/restart refuse while rpt.conf has errors unless confirmed;
  stop, reboot and power-off need a recent password. In `--dev`, restart and
  stop use the private instance's CLI; reboot is refused.
- **Allmon3** (`allmon3.ini` is allmon3:allmon3 0660) cannot be changed by
  the service; until the privileged helper (M4) the review lists the manual
  step (node rename, AMI secret).
- **Frontend:** Nodes page with first-run card and Add node wizard (number,
  password, configuration preset, interface, call sign, customizations,
  review); node page with General, Radio interface, Tuning (SSH command until
  M6), Access control and Customizations tabs; Asterisk › Settings (AMI
  secret, IAX port); Restart on the banner and the Asterisk page; Restart
  system / Shut down on the Overview. Every change goes through one review
  dialog (diffs per file, notes, errors), then offers to restart Asterisk.
- **Fixed during testing:** first run must ensure the channel driver and
  section even when the interface does not change (node-setup forces it);
  covered by a parity test.

## 19. Implementation decisions during M4 (2026-10-15)

- **Privileged helper** (`backend/asl_web_ui_priv/`, standard library only):
  `asl-web-ui-priv.socket` (`/run/asl-web-ui-priv/priv.sock`, asterisk 0600,
  `Accept=yes`) starts `asl-web-ui-priv@.service` as root per request. One JSON
  request in; `output` lines (progress) and one `result` out.
  - Authorization: the caller's pid/uid from `SO_PEERCRED`, the start time
    from `/proc/<pid>/stat` (field 22), then `pkcheck --action-id
    org.allstarlink.asl-web-ui.<command> --process pid,start,uid`. Actions are
    declared in `/usr/share/polkit-1/actions/org.allstarlink.asl-web-ui.policy`
    (default `auth_admin`); `50-asl-web-ui.rules` grants them to the asterisk
    user only. Verified on the dev box through the hardened service.
  - Commands: `backup.create/read/restore/delete/import`,
    `backup.read_include_list/write_include_list`, `factory.restore`,
    `file.read/write` (allowlist: `/etc/allmon3/allmon3.ini`),
    `asterisk.fix_ownership`. The web user name is logged, never trusted.
- **Backups** share `/var/asl-backups` and its include list with
  asl-backup-menu (same `ASL_YYYY-MM-DD_HHMM.tgz` names and format). Archives
  are `root:asterisk 0640` (asl-backup-menu makes them world-readable, and
  they hold passwords); the service reads them for download and upload.
- **Restore safety:** only members under an include-list path; absolute
  names, `..`, links leading outside, hard links, devices and FIFOs refused;
  set-id bits dropped; a parent directory that is a link elsewhere is not
  followed; files written atomically with the archive's owner; a
  `_before-restore` backup first. The dialog lists what will be written and
  what is skipped, before anything happens.
- **Factory reset** as asl-backup-menu (`apt-get install --reinstall
  asl3-asterisk-config` with confnew, remove `*.dpkg-old`, keep the AMI
  secret), plus a `_before-factory` backup. Verified on the dev box.
- **AllStarLink backup server**, as asl-backup-menu uses it: basic auth with
  savenode.conf's node and password (or ones entered on the page),
  `savenode.cgi` (POST, 2,000,000-byte limit), `getfile.cgi?NAME`, and the
  index page's `getfile.cgi` links. Downloads are staged in
  `/var/lib/asl-web-ui/staging` and filed by `backup.import`, which checks
  the archive. Tested against a fake server only (no real credentials here).
- **Jobs** (`modules/jobs.py`): restore, factory reset and cloud transfers
  return a job id at once and the page polls for progress, so nginx's 60 s
  proxy timeout never cuts them off. nginx's snippet allows 64 MB uploads.
- **Allmon3:** node renames and AMI secret changes read allmon3.ini through
  the helper, show its diff in the same review, write it after the Asterisk
  files (hash-checked) and restart allmon3.service. As node-setup, `pass` is
  changed only where it held the old secret.
- **Fix permissions:** a button in the editor and in the change review gives
  root-owned files back to the owner of /etc/asterisk (password re-entry).
- **--dev** runs the helper's commands in-process on a sandbox copy
  (`<state>/dev-root`); factory reset is refused there.
- **Found by tests:** an aiohttp `Response` is an empty mapping, so
  `if denied:` was always false and skipped the password re-entry check; now
  `is not None`. PatternFly's focus trap crashes a dialog with no focusable
  element (progress dialogs); the button stays focusable (`isAriaDisabled`).

## 20. Implementation decisions during M5 (2026-10-15)

- **Connectivity check** (`asl_web_ui/authcheck.py`): runs
  `asl-node-auth-check` as the service user (it allows asterisk), as a job,
  and caches the result in `/var/lib/asl-web-ui/connectivity.json`; the
  Overview's Health card shows the cached result. `--json` is used when
  `--help` mentions it; until then the text output is parsed into the same
  structure (sections config / public_ip / node, findings with level,
  message, the upstream spec's ids and their data). Patterns follow the
  tool's own format strings; the raw output is kept and shown.
- **Fix-it hints** in the page are keyed on finding ids (stock `1234:abcdef`
  placeholder, CGNAT, port forwarding, password, ...).
- **Basic checks** from asl-menu's System Diagnostics Menu: ping 8.8.8.8 (a
  job; ICMP datagram sockets work inside the sandbox because Debian's
  `ping_group_range` covers all groups), the registration server (HTTP GET
  with a 5 s connect limit, as asl-menu's `wget --spider`), Asterisk version
  and registrations (on the Asterisk page), the node list service
  (`asl3-update-nodelist`: shown as not installed when absent, which is the
  case on current ASL3 with DNS lookups; restart through polkit), and the
  installed packages (asl-show-version's `dpkg-query` patterns).
- Verified on the dev box through the hardened service.

## Mockup

[mockup/](mockup/) holds the source of the published mockup. To rebuild:

1. Download into one directory, from jsDelivr: `@patternfly/patternfly@6.6.0`
   `patternfly.min.css`, `assets/fonts/webfonts/fa-solid-900.woff2`, and the
   RedHatText, RedHatDisplay and RedHatMono `*VF.woff2` fonts.
2. Run `python3 -I build.py <that-dir> <out.html>`.

`smoke-test.js` loads the script with a stub DOM and renders every page:
`node smoke-test.js mockup.js`.

The mockup is a design tool, not product code.
