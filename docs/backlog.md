# Backlog

Work agreed but not yet scheduled. Newest first within each section.

## Tooling and packaging

### Managing Node.js and other software that does not come as a Debian package

*Added 2026-10-15 at the user's request.*

Work out how the project obtains, pins, updates and accounts for everything
it uses that is not a `.deb` from the Debian or AllStarLink repositories.
Today that is:

- **Node.js** (24.21.0) from nodejs.org, pinned with SHA-256 checksums in
  `builder/install-node.sh`, used by the builder image and by developers.
  Only needed to build the frontend; the installed package does not use it.
- **The npm dependency tree** (86 packages in `frontend/package-lock.json`),
  fetched from the npm registry with `npm ci`, limited to releases older
  than the `NPM_BEFORE` date in `frontend/Makefile`:
  - shipped in the package, compiled into `app.js` / `app.css`: React,
    PatternFly (react-core, react-icons, react-table), CodeMirror 6 and
    Lezer, xterm.js;
  - shipped as files: the Red Hat Display/Text/Mono fonts and PatternFly
    icon font and background images (`/usr/share/asl-web-ui/www/assets/`);
  - build tools only: TypeScript 7 and esbuild, which are native programs
    published as per-platform npm packages (`@typescript/typescript-*`,
    `@esbuild/*`).
- **The builder's base image**, `docker.io/<arch>/debian:<release>` from
  Docker Hub.

Questions to answer:

- Should Node.js and the build tools come from Debian (`nodejs`, `node-*`,
  `esbuild` packages), from a mirror under AllStarLink's control, or stay
  pinned upstream downloads? What about Debian 14?
- How do updates happen, and who notices security fixes in the npm tree
  (scheduled `npm audit`, Dependabot, a release checklist)?
- Should the npm tarballs and Node.js archive be cached or vendored, so a
  build does not depend on nodejs.org and the npm registry being reachable?
- Licensing: done 2026-10-15. `debian/copyright` lists every bundled npm
  package and the Red Hat fonts, and `frontend/build.mjs` fails the build
  when a bundled package has no stanza there.
- Debian policy prefers packaged libraries over embedded copies: decide
  whether that matters for the AllStarLink repository, and document the
  decision.

## Testing

*Carried over from the 2026-10-15 sessions.*

- AllStarLink cloud backups (list, upload, restore) against the real server;
  so far only a stand-in server was used.
- Allmon3 kept in step on a system where Allmon3's password equals the AMI
  secret (the case where it is rewritten).
- Hand-edited and older configurations beyond the stock files and nodes
  2102, 2104 and 40608.
- Frontend unit tests (Vitest), ESLint, browser tests (Playwright), and a full
  boot test on a virtual machine.

## Releases

- Version numbering for test releases (for example `0.1~beta1`); deferred by
  the user on 2026-10-15.
- A short note for testers (install, HTTPS, the `asl-web-ui` group, take a
  backup first, restarts run the startup macro, where to report problems).

## Upstream

- The changes requested in [upstream-changes.md](upstream-changes.md):
  numeric one-shot tuning displays in app_rpt, and app_rpt's tune save
  rewriting every included file.

### Self-signed certificate Apple devices can trust (#46)

*Added 2026-10-31. Confirmed 2026-11-01: Allan trusted a certificate with a
SAN in the Keychain and `.local` worked; the old certificate broke it again.
Implemented 2026-11-01; waiting on review.*

Safari refuses WebSockets to a server whose certificate the device does not
trust, even after the user accepts the page's warning ("The certificate for
this server is invalid"; the upgrade never reaches Apache). Seen on `.local`
with "Prevent cross-site tracking" on. Apple trusts a TLS server certificate
only with the names in a subjectAltName, extendedKeyUsage serverAuth and at
most 825 days (<https://support.apple.com/en-us/103769>); the first-boot
certificates had none of these.

Why the click-through does not cover the socket: in WebKit, page loads pick a
session through `sessionWrapperForTask`, while WebSocket tasks always use the
default session and their trust challenge reaches Safari through a separate
branch of `NetworkSessionCocoa::continueDidReceiveChallenge`. Safari's side is
closed; WebKit's registrable-domain code treats `.local` and `.home` alike.
Not a timing problem. Long-standing:
[WebKit bug 145819](https://bugs.webkit.org/show_bug.cgi?id=145819); Cockpit
documents it at <https://cockpit-project.org/running/safari>.

Pull requests, all opened 2026-11-01:

- **asl-web-ui #55**: banner when sockets keep failing; HTTPS page checks
  Apple's rules, offers the certificate download, trust steps and
  fingerprint, warns 30 days before expiry, and renews through the
  appliance's script.
- **asl3-appliance #25**: `/usr/sbin/asl3-self-signed-cert`, run by the
  postinst with `--if-needed` (replaces a certificate that breaks the rules,
  renews 30 days before expiry, never touches a CA-signed one) and gives
  Cockpit a copy in `/etc/cockpit/ws-certs.d/50-asl3-self-signed.cert`.
- **asl3-pi-image #27** and **ASL-Debian-ISO #1**: first boot uses that
  script, or makes the same certificate and Cockpit copy with openssl.
- Posted the explanation on #46:
  <https://github.com/AllStarLink/asl-web-ui/issues/46#issuecomment-6561986365>.

Still open:

- Nobody has looked at the new banners and HTTPS card in a browser.
- iPhone and iPad trust steps untested (asked Allan). iOS may want a CA
  certificate rather than this `CA:FALSE` one.
- No image built or booted with the first-boot change.
- asl-web-ui's text after "Stop using it" says Cockpit goes back to its own
  certificate; on an appliance it goes back to the shared self-signed one.
- Release order: the renew button and first boot use the script only once
  asl3-appliance ships it; until then first boot falls back to openssl.
- Declined 2026-11-01: a Server-Sent Events fallback for status.
