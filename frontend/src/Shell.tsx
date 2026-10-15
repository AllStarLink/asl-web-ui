import { ReactNode, useState } from "react";
import {
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
  PageToggleButton,
  MastheadBrand,
  MastheadLogo,
} from "@patternfly/react-core";
import AsteriskIcon from "@patternfly/react-icons/dist/esm/icons/asterisk-icon";
import BarsIcon from "@patternfly/react-icons/dist/esm/icons/bars-icon";
import TachometerAltIcon from "@patternfly/react-icons/dist/esm/icons/tachometer-alt-icon";
import UserIcon from "@patternfly/react-icons/dist/esm/icons/user-icon";

import { Star } from "./Brand";
import { go } from "./useRoute";

type NavEntry = { route: string; label: string; icon: ReactNode };

const NAV: NavEntry[] = [
  { route: "overview", label: "Overview", icon: <TachometerAltIcon /> },
  { route: "asterisk", label: "Asterisk", icon: <AsteriskIcon /> },
];

type Props = {
  user: string;
  hostname: string;
  route: string;
  onLogout: () => void;
  children: ReactNode;
};

// Cockpit-style frame: dark top bar with the host, dark navigation column.
export function Shell({ user, hostname, route, onLogout, children }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const base = route.split("/")[0];

  const masthead = (
    <Masthead className="asl-masthead">
      <MastheadMain>
        <MastheadToggle>
          <PageToggleButton
            variant="plain"
            aria-label="Navigation"
            isSidebarOpen={sidebarOpen}
            onSidebarToggle={() => setSidebarOpen((o) => !o)}
          >
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
    <PageSidebar isSidebarOpen={sidebarOpen} className="asl-sidebar">
      <PageSidebarBody>
        <nav aria-label="Main">
          <ul className="asl-nav">
            {NAV.map((n) => (
              <li key={n.route}>
                <button
                  type="button"
                  className={`asl-nav-link${base === n.route ? " current" : ""}`}
                  aria-current={base === n.route ? "page" : undefined}
                  onClick={() => go(n.route)}
                >
                  {n.icon}
                  <span>{n.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>
      </PageSidebarBody>
    </PageSidebar>
  );

  return (
    <Page masthead={masthead} sidebar={sidebar}>
      {children}
    </Page>
  );
}
