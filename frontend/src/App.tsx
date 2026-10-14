import { useEffect, useState } from "react";
import {
  Alert,
  Card,
  CardBody,
  CardTitle,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
  Masthead,
  MastheadBrand,
  MastheadLogo,
  MastheadMain,
  Nav,
  NavItem,
  NavList,
  Page,
  PageSection,
  PageSidebar,
  PageSidebarBody,
  Spinner,
  Title,
} from "@patternfly/react-core";
import CheckCircleIcon from "@patternfly/react-icons/dist/esm/icons/check-circle-icon";

type Health = { status: string; version: string };

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; health: Health }
  | { kind: "error"; message: string };

function useHealth(): HealthState {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  useEffect(() => {
    fetch("api/v1/health")
      .then(async (resp) => {
        if (!resp.ok) throw new Error(`The service answered with HTTP ${resp.status}.`);
        setState({ kind: "ok", health: (await resp.json()) as Health });
      })
      .catch((err: unknown) =>
        setState({ kind: "error", message: err instanceof Error ? err.message : String(err) }),
      );
  }, []);
  return state;
}

function ServiceStatus() {
  const state = useHealth();
  if (state.kind === "loading") return <Spinner size="md" aria-label="Checking the service" />;
  if (state.kind === "error") {
    return (
      <Alert variant="danger" isInline title="The asl-web-ui service is not responding">
        <p>{state.message}</p>
        <p>
          Check it with <code>systemctl status asl-web-ui.socket asl-web-ui.service</code>.
        </p>
      </Alert>
    );
  }
  return (
    <DescriptionList isHorizontal>
      <DescriptionListGroup>
        <DescriptionListTerm>Service</DescriptionListTerm>
        <DescriptionListDescription>
          <Label color="green" icon={<CheckCircleIcon />}>
            Running
          </Label>
        </DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>Service version</DescriptionListTerm>
        <DescriptionListDescription>{state.health.version}</DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>Interface version</DescriptionListTerm>
        <DescriptionListDescription>{__ASL_WEB_UI_VERSION__}</DescriptionListDescription>
      </DescriptionListGroup>
    </DescriptionList>
  );
}

export function App() {
  const masthead = (
    <Masthead>
      <MastheadMain>
        <MastheadBrand>
          <MastheadLogo component="span">AllStarLink</MastheadLogo>
        </MastheadBrand>
      </MastheadMain>
    </Masthead>
  );
  const sidebar = (
    <PageSidebar>
      <PageSidebarBody>
        <Nav aria-label="Main">
          <NavList>
            <NavItem itemId="overview" isActive>
              Overview
            </NavItem>
          </NavList>
        </Nav>
      </PageSidebarBody>
    </PageSidebar>
  );

  return (
    <Page masthead={masthead} sidebar={sidebar}>
      <PageSection>
        <Title headingLevel="h1">ASL Web UI</Title>
        <Content component="p">
          The package is installed and the service is reachable. Node management, diagnostics,
          backups and tuning arrive in later milestones.
        </Content>
      </PageSection>
      <PageSection>
        <Card>
          <CardTitle>Status</CardTitle>
          <CardBody>
            <ServiceStatus />
          </CardBody>
        </Card>
      </PageSection>
    </Page>
  );
}
