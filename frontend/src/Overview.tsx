import {
  Card,
  CardBody,
  CardFooter,
  CardTitle,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Gallery,
  Label,
  List,
  ListItem,
  PageSection,
  Spinner,
  Title,
  Button,
} from "@patternfly/react-core";
import CheckCircleIcon from "@patternfly/react-icons/dist/esm/icons/check-circle-icon";
import ExclamationTriangleIcon from "@patternfly/react-icons/dist/esm/icons/exclamation-triangle-icon";
import LockIcon from "@patternfly/react-icons/dist/esm/icons/lock-icon";
import TimesCircleIcon from "@patternfly/react-icons/dist/esm/icons/times-circle-icon";

import { Status, SystemInfo } from "./api";
import { duration } from "./format";
import { go } from "./useRoute";

export function AsteriskState({ status }: { status: Status | null }) {
  if (!status) return <Spinner size="sm" aria-label="Loading" />;
  const a = status.asterisk;
  if (a.state !== "active") return <Label color="red" icon={<TimesCircleIcon />}>Stopped</Label>;
  if (!a.reachable) return <Label color="orange" icon={<ExclamationTriangleIcon />}>Not responding</Label>;
  return <Label color="green" icon={<CheckCircleIcon />}>Running</Label>;
}

export function RegistrationLabel({ node }: { node: Status["nodes"][number] }) {
  if (node.private) return <Label icon={<LockIcon />}>Private · not registered</Label>;
  if (node.registration === "Registered") return <Label color="green" icon={<CheckCircleIcon />}>Registered</Label>;
  return (
    <Label color="orange" icon={<ExclamationTriangleIcon />}>
      {node.registration ?? "No registration"}
    </Label>
  );
}

function Health({ status }: { status: Status | null }) {
  if (!status) return <Spinner size="md" aria-label="Loading" />;
  const items: { ok: boolean; text: string; sub?: string }[] = [];
  const a = status.asterisk;
  items.push(
    a.state === "active" && a.reachable
      ? { ok: true, text: "Asterisk is running", sub: `for ${duration(a.uptime)}` }
      : { ok: false, text: a.state === "active" ? "Asterisk is not responding" : "Asterisk is not running", sub: status.error ?? undefined },
  );
  for (const n of status.nodes.filter((n) => !n.private)) {
    items.push(
      n.registration === "Registered"
        ? { ok: true, text: `Node ${n.node} is registered` }
        : { ok: false, text: `Node ${n.node} is not registered`, sub: n.registration ?? "No registration attempt" },
    );
  }
  return (
    <List isPlain className="asl-health">
      {items.map((i) => (
        <ListItem key={i.text} icon={i.ok ? <CheckCircleIcon className="asl-ok" /> : <ExclamationTriangleIcon className="asl-warn" />}>
          {i.text}
          {i.sub && <div className="asl-sub">{i.sub}</div>}
        </ListItem>
      ))}
    </List>
  );
}

type Props = { status: Status | null; system: SystemInfo | null };

export function Overview({ status, system }: Props) {
  return (
    <>
      <PageSection className="asl-page-head">
        <Title headingLevel="h1">{system?.hostname ?? "Overview"}</Title>
        <Content component="p">AllStarLink node server overview.</Content>
      </PageSection>
      <PageSection>
        <Gallery hasGutter minWidths={{ default: "100%", lg: "28rem" }}>
          <Card>
            <CardTitle>Health</CardTitle>
            <CardBody>
              <Health status={status} />
            </CardBody>
          </Card>
          <Card>
            <CardTitle>Nodes</CardTitle>
            <CardBody>
              {!status ? (
                <Spinner size="md" aria-label="Loading" />
              ) : status.nodes.length === 0 ? (
                <Content component="p">No nodes are running.</Content>
              ) : (
                status.nodes.map((n) => (
                  <div className="asl-node-row" key={n.node}>
                    <b>{n.node}</b>
                    <RegistrationLabel node={n} />
                  </div>
                ))
              )}
            </CardBody>
          </Card>
          <Card>
            <CardTitle>Asterisk</CardTitle>
            <CardBody>
              <DescriptionList isHorizontal isCompact>
                <DescriptionListGroup>
                  <DescriptionListTerm>Status</DescriptionListTerm>
                  <DescriptionListDescription>
                    <AsteriskState status={status} />
                  </DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>Running for</DescriptionListTerm>
                  <DescriptionListDescription>{duration(status?.asterisk.uptime)}</DescriptionListDescription>
                </DescriptionListGroup>
              </DescriptionList>
            </CardBody>
            <CardFooter>
              <Button variant="link" isInline onClick={() => go("asterisk")}>
                Asterisk details
              </Button>
            </CardFooter>
          </Card>
          <Card>
            <CardTitle>System</CardTitle>
            <CardBody>
              <DescriptionList isHorizontal isCompact>
                {[
                  ["Hostname", system?.hostname],
                  ["Operating system", system?.os],
                  ["AllStarLink (app_rpt)", status?.versions.app_rpt],
                  ["Asterisk", status?.versions.asterisk],
                  ["asl-web-ui", system?.asl_web_ui],
                  ["Up for", system ? duration(system.uptime) : undefined],
                ].map(([term, value]) => (
                  <DescriptionListGroup key={term}>
                    <DescriptionListTerm>{term}</DescriptionListTerm>
                    <DescriptionListDescription>{value ?? "—"}</DescriptionListDescription>
                  </DescriptionListGroup>
                ))}
              </DescriptionList>
            </CardBody>
          </Card>
        </Gallery>
      </PageSection>
    </>
  );
}
