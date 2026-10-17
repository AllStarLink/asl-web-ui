# asl-web-ui

A web interface for managing AllStarLink 3 node servers with a
browser UI in the style of Cockpit, built with PatternFly.

> [!CAUTION]
> This package is under heavy development and most assuredly
> has bugs. Don't run this on a node that you cannot easily
> fix or rebuild if something goes wrong.

The following is currently supported (almost feature-parity with asl-menu):

* Basic Node Configuration
  * Supported node channels: SimpleUSB, USBRadio, Hubs/Pseudo, Voter/RTCM
  * "Shortcut"/Customizations for some commercial nodes
  * Web-based audio tuning for SimpleUSB and USBRadio (usbradio has known issues/deficiencies)
  * Access-control management
  * SA818 programming interface
* Basic Asterisk Management
  * Start/restart Asterisk
  * AMI password management and synchronization with Allmon3
  * IAX port configuration
  * Web-based asterisk console
* Allmon3 Management
  * Node add/remove
  * User management
  * Web Settings
  * Advanced editor for all other file-based customizations except custom CSS
* Diagnostics
  * Web-based view of `asl-node-auth-check`
  * Basic network diagnostics
  * Package lists
  * Asterisk log view/export
* Node Backup Management
* TLS certificate automation with Let's Encrypt to remove SSL browser
errors
* "Expert Mode" for advanced editing of `/etc/asterisk` and `/etc/allmon3` files
* Syntax checker for Asterisk configuration files and a normalization
engine to make customized files editable with asl-web-ui

Major items remaining before release:

* Wireguard / 44Net Connect Interface (maybe)
* Tighter integration with the ASL3 Appliance package
* All important bugs

## Installing

asl-web-ui is distributed as a Debian package for AllStarLink 3 on Debian 13
(trixie). Currently, it only lives in the "devel" package repo. To install:

```bash
asl-repo-switch -l devel
apt update
apt install -y asl-web-ui
```

### Authentication Config Post-Install

The authentication fo asl-web-ui is via system accounts in the same
manner as Cockpit. Currently, each account who should manage the
node must be manually added to the `asl-web-ui` group:

```bash
sudo usermod -aG asl-web-ui <username>
```

ASL3 Appliances will have a mechanism to auto-add system accounts
when the software is fully released.

### Access Must be via HTTPS

Make sure the web server serves the site over HTTPS. asl-web-ui refuses
logins over plain HTTP.

* **Apache:** the package enables its configuration automatically.

* **nginx:** add `include /etc/asl-web-ui/nginx.conf;` inside the
     `server { }` block of your site, then reload nginx.

Open `https://<your-node>/asl-web-ui/`.


### NGINX Proxy Configuration

If nginx owns ports 80/443 and Apache (with asl-web-ui) listens elsewhere,
for example on 8443 on the same machine, nginx can pass `/asl-web-ui/`
through to it. Proxy to Apache over HTTPS (asl-web-ui uses the scheme
Apache sees) and keep the browser's `Host` header, which asl-web-ui
compares with the `Origin` of requests.

Inside `http { }`, for example in `/etc/nginx/conf.d/websocket.conf`:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

Inside the HTTPS `server { }` block:

```nginx
    location /asl-web-ui/ {
        proxy_pass https://127.0.0.1:8443;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 1h;
        client_max_body_size 64m;
    }
```

nginx does not verify Apache's certificate by default, which is fine for
`127.0.0.1`. asl-web-ui then sees nginx's address as the client address
(for example in the PAM log) unless Apache's `mod_remoteip` is set to
trust nginx.

## Building Locally

Build the package in the builder container (Podman by default, no
publishing); see [Developing from source](#developing-from-source) for the
full setup:

```bash
make podman-deb
```

Packages are written to `../_debs/`. The builder image provides a pinned,
checksum-verified Node.js for the frontend; `dpkg-buildpackage` itself never
needs Node.js.

Other targets:

| Target | Purpose |
|---|---|
| `make frontend` | Build the browser bundle into `frontend/dist/` (needs Node.js) |
| `make check` | Run the backend tests and the frontend type check |
| `make deb` | Build the package directly (used inside the builder) |

## Developing from source

These steps set up a development machine on which you can run asl-web-ui
from a checkout, run every test suite, and build and try the package.

### 1. What you need

* **Debian 13 (trixie)**, amd64 or arm64, with the AllStarLink 3 package
  repository configured (the `asl-apt-repos` package; see the ASL3 manual).
  A virtual machine or a spare node is fine.

* **AllStarLink itself**, for the private test Asterisk, the conformance
  tests and the parity tests:

```bash
sudo apt install asl3-asterisk asl3-menu
```

* **Python and the backend's libraries** (the same versions the package
  uses):

```bash
sudo apt install python3 python3-aiohttp python3-aiohttp-session \
    python3-pytest python3-pytest-aiohttp python3-hypothesis python3-argon2 pandoc
```

* **Node.js and npm**, only to build the browser code (see
  [Installing Node.js](#installing-nodejs) below). Packages built with
  `make podman-deb` get Node.js from the builder image, so you need it
  locally only for frontend work.

* **Podman** (or Docker), to build the Debian package:

```bash
sudo apt install podman
```

* **Firefox** (`firefox-esr`), for `tests/e2e/screenshot.py`.

```bash
sudo apt install firefox-esr
```

* To try an installed package: **Apache or nginx with HTTPS**.

### 2. Installing Node.js

The package builds use one pinned Node.js release, installed by
`builder/install-node.sh`. Use the same script on your machine, so that
`node` and `npm` match the builds exactly; the version and the SHA-256
checksums of the release archives are kept in that script and nowhere else.

Install the tools the script uses (most systems have them):

```bash
sudo apt install curl xz-utils
```

From the top of your checkout (`git clone`, step 2 below), install
   Node.js into */opt/node*:

```bash
sudo builder/install-node.sh
```

   The script downloads the release for your architecture (amd64 or arm64)
   from nodejs.org, refuses it unless its checksum matches the pinned one,
   and unpacks it. It ends by printing the installed versions, for example
   `Installed: node v24.21.0, npm 11.19.0 in /opt/node`. To use another
   directory, give it as an argument (`sudo builder/install-node.sh
   /opt/node-24`).

Put it first on your `PATH`, for your account:

```bash
echo 'export PATH=/opt/node/bin:$PATH' >> ~/.bashrc
```

then log out and back in (or run `. ~/.bashrc`).

Check:

```bash
node --version     # v24.21.0
npm --version      # 11.19.0
```

**Updating:** when the pinned version changes in `builder/install-node.sh`,
run `sudo builder/install-node.sh` again. It replaces the earlier
installation in */opt/node* (and refuses to touch a directory that holds
anything other than a Node.js installation).

**Removing:** `sudo rm -rf /opt/node` and delete the `PATH` line from
*~/.profile*.

Debian's own `nodejs` package (Node.js 20, npm 9) also builds the frontend;
the bundle comes out the same, because the dependencies come from the lock
file. Use the pinned release anyway when you change dependencies or the
build, so that you see what the package builds see. With */opt/node/bin*
first on your `PATH`, Debian's package can stay installed.

To move to a newer Node.js: change `NODE_VERSION` and both checksums in
`builder/install-node.sh` (from the release's `SHASUMS256.txt`, after checking
that file's signature as described in Node.js's README), rebuild with
`make podman-deb`, and rerun the script on your machine.

### 3. Get the code and build the frontend

```bash
git clone https://github.com/AllStarLink/asl-web-ui.git
cd asl-web-ui
make frontend
```

`make frontend` installs the npm packages exactly as listed in
`frontend/package-lock.json` (`npm ci`, with install scripts disabled) and
writes the bundle to `frontend/dist/`. Run it again after changing anything
under `frontend/`.

### 4. Run it in development mode

Development mode serves the UI and the API on `http://127.0.0.1:8099/` with a
fake login (user `dev`, password `dev`). It works best with a private,
unprivileged Asterisk built from the installed ASL packages, which never
touches the system's Asterisk or */etc/asterisk*:

```bash
tests/asterisk/instance.sh start /tmp/asl-dev-asterisk
cd backend
python3 -m asl_web_ui.server --dev \
    --asterisk-conf /tmp/asl-dev-asterisk/etc/asterisk.conf
```

Open http://127.0.0.1:8099/ and log in as `dev` / `dev`. Stop the private
Asterisk with `tests/asterisk/instance.sh stop /tmp/asl-dev-asterisk`.

In development mode:

- the configuration pages edit the private instance's files
  (*/tmp/asl-dev-asterisk/etc*), with snapshots next to them;
- the privileged commands (backups, restores) run unprivileged on a sandbox
  copy of the configuration under the state directory; reboot, power off and
  the factory reset are refused;
- `--dev` refuses to run from the installed package or as the asterisk user.

### 4. Develop against a real node

To try your code against a node with real hardware without installing
anything there, copy the checkout (or just `backend/` and `frontend/dist/`)
to the node and run, as an ordinary user with passwordless sudo:

```bash
cd backend
python3 -m asl_web_ui.server --dev \
    --asterisk-cmd "sudo -n /usr/sbin/asterisk" \
    --state-dir ~/asl-web-ui-state
```

then tunnel to it from your computer and open http://127.0.0.1:8099/:

```bash
ssh -N -L 8099:127.0.0.1:8099 user@node
```

The server listens only on the node's localhost. It talks to the node's real
Asterisk, so radio settings and Asterisk restarts are real: copy
*/etc/asterisk* first, and remember that restarting Asterisk runs the node's
startup macro (it may link to other nodes).

### 5. Run the tests

From the top of the checkout:

| Command | What it checks | Needs |
|---|---|---|
| `make check` | backend unit and API tests, frontend type check | the Python libraries; Node.js |
| `python3 -m pytest tests/conformance` | the configuration engine reads files exactly as ASL's Asterisk does | `asl3-asterisk` (runs a private Asterisk) |
| `python3 -m pytest tests/parity` | node changes leave Asterisk configured exactly as asl3-menu's `node-setup` would | `asl3-menu`; `apt-get download` access (the stock packages are fetched once into *~/.cache/asl-web-ui-tests*) |
| `tests/e2e/smoke.py URL USER PASSWORD-FILE [--insecure]` | an installed package end to end, through the web server, with a real login | an installed package and a test account |
| `tests/e2e/screenshot.py URL OUT.png [--cookie name=value] [--insecure]` | renders a page in headless Firefox and prints browser errors | Firefox |

`make check` also runs inside the builder when the package is built, so a
package never builds with failing unit tests.

### 6. Build and try the package

```bash
make podman-deb
```

The package is written to `../_debs/`. Install it with its dependencies:

```bash
sudo apt install ../_debs/asl-web-ui_*.deb
```

Then:

1. Make sure the web server has HTTPS. For a test machine, Apache's
   self-signed default site is enough:

```bash
sudo a2enmod ssl
sudo a2ensite default-ssl
sudo systemctl reload apache2
```

   With nginx, add `include /etc/asl-web-ui/nginx.conf;` to the HTTPS
   `server { }` block and reload nginx.

1. Create or choose a test account and put it in the group:

```bash
sudo usermod -aG asl-web-ui <username>
```

1. Open `https://<host>/asl-web-ui/`, or run the smoke test with the
   account's password in a file only you can read:

```bash
tests/e2e/smoke.py https://localhost/asl-web-ui/ <username> \
    ~/.asl-web-ui-test-password --insecure
```

Reinstalling the package restarts the service, which logs everyone out
(sessions are kept in memory).

`builder/dockerbuild.sh` is the CI script used by the AllStarLink build
runners; it builds **and publishes** packages and is not meant for local
use.

### 7. Changing frontend dependencies

Edit `frontend/package.json`, then regenerate the lock file:

```bash
make -C frontend lock
```

npm only picks versions published before the date in `frontend/Makefile`
(`NPM_BEFORE`), so new releases are taken deliberately. Move that date
forward when upgrading.

### More

* `docs/DESIGN.md` describes the architecture and `docs/design-notes.md` the
  decisions behind it; read them before larger changes. Open work is in
  `docs/backlog.md`.

* Contributions with AI involvement follow [AGENTS.md](AGENTS.md) and
  AllStarLink's ASL003 practice.

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
