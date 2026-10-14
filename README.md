# asl-web-ui

A web interface for managing AllStarLink 3 node servers. It replaces the
text menus of [asl3-menu](https://github.com/AllStarLink/asl3-menu) with a
browser UI in the style of Cockpit, built with PatternFly.

**Status:** early development. Milestone M0 (package skeleton) is in progress;
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

`builder/dockerbuild.sh` is the CI script used by the AllStarLink build
runners; it builds **and publishes** packages and is not meant for local use.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | The Python (aiohttp) service and its tests |
| `frontend/` | The React + PatternFly 6 browser application |
| `conf/` | Default settings and the Apache configuration snippet |
| `doc/` | Man pages (Markdown, converted with pandoc) |
| `debian/` | Debian packaging, including the systemd units |
| `builder/` | The build container |
| `docs/` | Design documents, the mockup, and research notes |

## License

GNU Affero General Public License, version 3. See [LICENSE](LICENSE).
