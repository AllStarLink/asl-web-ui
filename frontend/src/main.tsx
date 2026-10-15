import "@patternfly/react-core/dist/styles/base.css";
import "./shell.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { followSystemTheme } from "./theme";

// An address with a doubled slash (https://host//asl-web-ui/) still loads the
// page, but the session cookie belongs to /asl-web-ui/, so the browser would
// not send it with API requests and every page would ask to log in (issue
// #12). Reload at the normalized address instead.
const path = location.pathname.replace(/\/{2,}/g, "/");
if (path !== location.pathname) {
  location.replace(location.origin + path + location.search + location.hash);
}

followSystemTheme();

const root = document.getElementById("root");
if (root && path === location.pathname) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
