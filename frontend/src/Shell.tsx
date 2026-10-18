import { ReactNode, useContext, useState } from "react";
import {
  Alert,
  Button,
  Dropdown,
  DropdownItem,
  DropdownList,
  MenuToggle,
  Page,
  PageSidebar,
  PageSidebarBody,
  Masthead,
  MastheadMain,
  MastheadContent,
  MastheadToggle,
  PageContext,
  PageSection,
  PageToggleButton,
  MastheadBrand,
  MastheadLogo,
} from "@patternfly/react-core";
import AsteriskIcon from "@patternfly/react-icons/dist/esm/icons/asterisk-icon";
import BroadcastTowerIcon from "@patternfly/react-icons/dist/esm/icons/broadcast-tower-icon";
import BarsIcon from "@patternfly/react-icons/dist/esm/icons/bars-icon";
import FileCodeIcon from "@patternfly/react-icons/dist/esm/icons/file-code-icon";
import GlobeRouteIcon from "@patternfly/react-icons/dist/esm/icons/globe-route-icon";
import NetworkIcon from "@patternfly/react-icons/dist/esm/icons/network-icon";
import HistoryIcon from "@patternfly/react-icons/dist/esm/icons/history-icon";
import LockIcon from "@patternfly/react-icons/dist/esm/icons/lock-icon";
import MonitoringIcon from "@patternfly/react-icons/dist/esm/icons/monitoring-icon";
import StethoscopeIcon from "@patternfly/react-icons/dist/esm/icons/stethoscope-icon";
import TachometerAltIcon from "@patternfly/react-icons/dist/esm/icons/tachometer-alt-icon";
import WifiIcon from "@patternfly/react-icons/dist/esm/icons/wifi-icon";
import UserIcon from "@patternfly/react-icons/dist/esm/icons/user-icon";

import { Status } from "./api";
import { useAsteriskControl } from "./AsteriskControl";
import { Star } from "./Brand";
import { useDocumentTitle } from "./title";
import { go } from "./useRoute";

type NavEntry = { route: string; label: string; icon: ReactNode; expert?: boolean };

const NAV: NavEntry[] = [
  { route: "overview", label: "Overview", icon: <TachometerAltIcon /> },
  { route: "nodes", label: "Nodes", icon: <NetworkIcon /> },
  { route: "asterisk", label: "Asterisk", icon: <AsteriskIcon /> },
  { route: "allmon3", label: "Allmon3", icon: <MonitoringIcon /> },
  { route: "hardware", label: "Hardware", icon: <BroadcastTowerIcon /> },
  { route: "diagnostics", label: "Diagnostics", icon: <StethoscopeIcon /> },
  { route: "backups", label: "Backups", icon: <HistoryIcon /> },
  { route: "https", label: "HTTPS", icon: <LockIcon /> },
];

const NETWORKING: NavEntry[] = [
  { route: "network", label: "Network", icon: <WifiIcon /> },
  { route: "44net", label: "44Net Connect", icon: <GlobeRouteIcon /> },
];

// Kept apart, at the bottom, so that newcomers reach for the guided pages first.
const ADVANCED: NavEntry[] = [{ route: "config", label: "Manual Config Edit", icon: <FileCodeIcon />, expert: true }];

// The name of the page at a route, for the browser tab title: the
// navigation label, or the node or file being edited.
function pageName(route: string): string {
  const [base, sub, third] = route.split("/");
  const file = (name: string) => {
    try {
      return decodeURIComponent(name);
    } catch {
      return name;
    }
  };
  if (base === "nodes" && sub) return `Node ${sub}`;
  if (base === "allmon3" && sub === "files" && third) return file(third);
  if (base === "config" && sub === "~allmon3" && third) return file(third);
  if (base === "config" && sub === "~sa818") return "sa818.conf";
  if (base === "config" && sub) return file(sub);
  const key = base === "sa818" ? "hardware" : base;
  return [...NAV, ...NETWORKING, ...ADVANCED].find((n) => n.route === key)?.label ?? "Overview";
}

type Props = {
  user: string;
  hostname: string;
  route: string;
  status: Status | null;
  onLogout: () => void;
  children: ReactNode;
};

// Navigation links. On narrow screens the sidebar overlays the page, so it
// closes again after a link is chosen.
function NavLinks({ base, entries }: { base: string; entries: NavEntry[] }) {
  const { isMobile, isSidebarOpen, onSidebarToggle } = useContext(PageContext);
  return (
    <ul className="asl-nav">
      {entries.map((n) => (
        <li key={n.route}>
          <button
            type="button"
            className={`asl-nav-link${base === n.route ? " current" : ""}`}
            aria-current={base === n.route ? "page" : undefined}
            onClick={() => {
              go(n.route);
              if (isMobile && isSidebarOpen) onSidebarToggle();
            }}
          >
            {n.icon}
            <span>{n.label}</span>
            {n.expert && <span className="asl-nav-badge">Expert</span>}
          </button>
        </li>
      ))}
    </ul>
  );
}

// Cockpit-style frame: dark top bar with the host, dark navigation column.
// PatternFly manages the sidebar: open on wide screens, closed on phones
// until the menu button is pressed.
// Configuration files changed after Asterisk started, so they are not all in
// effect yet.
function RestartPending({ status }: { status: Status | null }) {
  const [controlElement, control] = useAsteriskControl();
  const changed = status?.config?.changed ?? [];
  if (!status?.asterisk.reachable || changed.length === 0) return null;
  const errors = status.config.rpt_errors;
  return (
    <PageSection className="asl-banner">
      {controlElement}
      <Alert
        variant={errors ? "danger" : "info"}
        isInline
        title={errors ? "Configuration changed, and rpt.conf has errors" : "Configuration changed since Asterisk started"}
        actionLinks={
          <>
            {errors > 0 && (
              <Button variant="link" isInline onClick={() => go("config/rpt.conf")}>
                Open rpt.conf
              </Button>
            )}
            <Button variant="link" isInline onClick={() => void control("restart")}>
              Restart Asterisk
            </Button>
          </>
        }
      >
        Changed: {changed.slice(0, 6).join(", ")}
        {changed.length > 6 ? ` and ${changed.length - 6} more` : ""}.{" "}
        {errors
          ? "Restarting or reloading Asterisk now would take every node off the air."
          : "Some changes take effect only when Asterisk restarts."}
      </Alert>
    </PageSection>
  );
}

export function Shell({ user, hostname, route, status, onLogout, children }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const base = route.split("/")[0] === "sa818" ? "hardware" : route.split("/")[0];
  useDocumentTitle(pageName(route), hostname);

  const masthead = (
    <Masthead className="asl-masthead">
      <MastheadMain>
        <MastheadToggle>
          <PageToggleButton variant="plain" aria-label="Navigation">
            <BarsIcon />
          </PageToggleButton>
        </MastheadToggle>
        <MastheadBrand>
          <MastheadLogo href="#/overview" className="asl-masthead-brand">
            <Star />
            <span>
              <b>AllStarLink</b>
              <small>
                {user}@{hostname}
              </small>
            </span>
          </MastheadLogo>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <div className="asl-masthead-tools">
          <Dropdown
            isOpen={menuOpen}
            onOpenChange={setMenuOpen}
            popperProps={{ position: "right" }}
            toggle={(ref) => (
              <MenuToggle ref={ref} variant="plainText" icon={<UserIcon />} onClick={() => setMenuOpen((o) => !o)} isExpanded={menuOpen}>
                {user}
              </MenuToggle>
            )}
          >
            <DropdownList>
              <DropdownItem onClick={onLogout}>Log out</DropdownItem>
            </DropdownList>
          </Dropdown>
        </div>
      </MastheadContent>
    </Masthead>
  );

  const sidebar = (
    <PageSidebar className="asl-sidebar">
      <PageSidebarBody>
        <nav aria-label="Main">
          <NavLinks base={base} entries={NAV} />
          <div className="asl-nav-section">Networking</div>
          <NavLinks base={base} entries={NETWORKING} />
          <div className="asl-nav-section">Advanced</div>
          <NavLinks base={base} entries={ADVANCED} />
        </nav>
      </PageSidebarBody>
    </PageSidebar>
  );

  return (
    <Page masthead={masthead} sidebar={sidebar} isManagedSidebar>
      <RestartPending status={status} />
      {children}
    </Page>
  );
}
