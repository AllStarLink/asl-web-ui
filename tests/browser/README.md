# Isolated Hardware identity check

Build `frontend/dist` first (`npm run typecheck && npm run build` in frontend).
With Playwright available to Node and Chromium installed, run from the checkout:

```sh
node tests/browser/hardware-identity.cjs
```

`CHROMIUM_PATH` overrides `/usr/bin/chromium`. All HTTP and WebSocket traffic is
intercepted. Synthetic fixtures cover a saved serial alias and changing from
SR110U to SA818S using **Look again**. No programming request is permitted.
No live node, RF, external website or screenshot is used by this check.
