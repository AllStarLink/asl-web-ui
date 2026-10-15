# asl-web-ui

A web interface for managing AllStarLink 3 node servers. It replaces the
text menus of [asl3-menu](https://github.com/AllStarLink/asl3-menu) with a
browser UI in the style of Cockpit, built with PatternFly.

**Status:** early development. Milestones M0 (package skeleton), M1 (login,
shell, status and console), M2 (Manual Config Edit), M3 (nodes, Asterisk
settings and restart), M4 (backups, privileged helper), M5 (diagnostics),
M6 (radio interface tuning; hardware check pending) and M7 (hardening) are done;
see [docs/DESIGN.md](docs/DESIGN.md) for the design and the milestone plan.

## Installing

asl-web-ui is distributed as a Debian package for AllStarLink 3 on Debian 13
(trixie). After installing it:

1. Add each person who should manage the node to the `asl-web-ui` group:

       sudo usermod -aG asl-web-ui <username>

2. Make sure the web server serves the site over HTTPS. asl-web-ui refuses
   logins over plain HTTP.
   - **Apache:** the package enables its configuration automatically.
   - **nginx:** add `include /etc/asl-web-ui/nginx.conf;` inside the
     `server { }` block of your site, then reload nginx.
3. Open `https://<your-node>/asl-web-ui/`.

## Building

Build the package in the builder container (Podman by default, no publishing):

    make podman-deb

Packages are written to `../_debs/`. The builder image provides a pinned,
checksum-verified Node.js for the frontend; `dpkg-buildpackage` itself never
needs Node.js.

Other targets:

| Target | Purpose |
|---|---|
| `make frontend` | Build the browser bundle into `frontend/dist/` (needs Node.js) |
| `make check` | Run the backend tests and the frontend type check |
| `make deb` | Build the package directly (used inside the builder) |

## Development

Run the backend with a fake login (user `dev`, password `dev`) and a private,
unprivileged Asterisk built from the installed ASL packages:

    tests/asterisk/instance.sh start /tmp/asl-dev-asterisk
    make frontend
    cd backend && python3 -m asl_web_ui.server --dev \
        --asterisk-conf /tmp/asl-dev-asterisk/etc/asterisk.conf

Then open http://127.0.0.1:8099/. `--dev` refuses to run from the installed
package or as the asterisk user.

Checks against an installed package:

    tests/e2e/smoke.py https://<host>/asl-web-ui/ <user> <password-file> [--insecure]
    tests/e2e/screenshot.py <url> out.png [--cookie name=value] [--insecure]

How the ASL-patched Asterisk reads configuration files is pinned down by
conformance tests that ask a private Asterisk directly (no root needed):

    python3 -m pytest tests/conformance

Node changes must leave Asterisk with the same configuration as asl3-menu's
node-setup; the parity tests run node-setup's own functions next to the
planner (they download the stock packages once with `apt-get download`):

    python3 -m pytest tests/parity

`builder/dockerbuild.sh` is the CI script used by the AllStarLink build
runners; it builds **and publishes** packages and is not meant for local use.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | The Python (aiohttp) service, its two root helpers (login, privileged commands) and their tests |
| `frontend/` | The React + PatternFly 6 browser application |
| `conf/` | Default settings, systemd units, PAM, polkit, Apache and nginx snippets |
| `doc/` | Man pages (Markdown, converted with pandoc) |
| `debian/` | Debian packaging |
| `tests/` | Conformance tests against a real Asterisk, end-to-end checks |
| `builder/` | The build container |
| `docs/` | Design documents, the mockup, and research notes |

## License

GNU Affero General Public License, version 3. See [LICENSE](LICENSE).
