# Isolated backup UI check

Build frontend/dist (`npm run typecheck && npm run build` under frontend).
With Playwright available to Node and Chromium installed:

```sh
node tests/browser/backup-coverage.cjs
```

`CHROMIUM_PATH` overrides `/usr/bin/chromium`. All network requests are mocked.
Checks customized-list warning, edit/readback clearing it, and idle/size guidance.
Refreshes two desktop screenshots under .github/screenshots using fabricated
example data only. It does not make a real backup, restore files or stop services.
