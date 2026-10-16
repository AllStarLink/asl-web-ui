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

- USBRadio with a radio on flat discriminator audio: DSP squelch, CTCSS
  decoding, and successful calibrations (40608's radio decodes CTCSS itself,
  so it cannot show these).
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
  `asl-node-auth-check --json`, numeric one-shot tuning displays in
  app_rpt, and app_rpt's tune save rewriting every included file.
