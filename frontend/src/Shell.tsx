import { ReactNode, useContext, useState } from "react";
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
  PageContext,
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

// Navigation links. On narrow screens the sidebar overlays the page, so it
// closes again after a link is chosen.
function NavLinks({ base }: { base: string }) {
  const { isMobile, isSidebarOpen, onSidebarToggle } = useContext(PageContext);
  return (
    <ul className="asl-nav">
      {NAV.map((n) => (
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
          </button>
        </li>
      ))}
    </ul>
  );
}

// Cockpit-style frame: dark top bar with the host, dark navigation column.
// PatternFly manages the sidebar: open on wide screens, closed on phones
// until the menu button is pressed.
export function Shell({ user, hostname, route, onLogout, children }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const base = route.split("/")[0];

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
          <NavLinks base={base} />
        </nav>
      </PageSidebarBody>
    </PageSidebar>
  );

  return (
    <Page masthead={masthead} sidebar={sidebar} isManagedSidebar>
      {children}
    </Page>
  );
}
