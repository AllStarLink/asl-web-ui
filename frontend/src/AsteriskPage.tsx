import {
  Button,
  Card,
  CardFooter,
  CardBody,
  CardTitle,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Gallery,
  PageSection,
  Spinner,
  Tab,
  Tabs,
  TabTitleText,
  Title,
} from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";

import { Registration, Status } from "./api";
import { useAsteriskControl } from "./AsteriskControl";
import { AsteriskSettings } from "./AsteriskSettings";
import { Console } from "./Console";
import { duration } from "./format";
import { AsteriskState } from "./Overview";
import { go } from "./useRoute";

function Registrations({ title, regs }: { title: string; regs: Registration[] }) {
  return (
    <>
      <Title headingLevel="h3" size="md" className="asl-subhead">
        {title}
      </Title>
      {regs.length === 0 ? (
        <Content component="p" className="asl-sub">
          None.
        </Content>
      ) : (
        <Table aria-label={title} variant="compact">
          <Thead>
            <Tr>
              <Th>Node</Th>
              <Th>Server</Th>
              <Th>Your address</Th>
              <Th>Refresh</Th>
              <Th>State</Th>
            </Tr>
          </Thead>
          <Tbody>
            {regs.map((r) => (
              <Tr key={`${r.host}-${r.username}`}>
                <Td dataLabel="Node">{r.username}</Td>
                <Td dataLabel="Server">{r.host}</Td>
                <Td dataLabel="Your address">{r.perceived}</Td>
                <Td dataLabel="Refresh">{r.refresh ?? "—"} s</Td>
                <Td dataLabel="State">{r.state}</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </>
  );
}

function ServiceButtons({ status }: { status: Status | null }) {
  const [element, control] = useAsteriskControl();
  const running = status?.asterisk.state === "active";
  return (
    <div className="asl-buttons">
      {element}
      {running ? (
        <>
          <Button variant="secondary" onClick={() => control("restart")}>Restart</Button>
          <Button variant="secondary" isDanger onClick={() => control("stop")}>Stop</Button>
        </>
      ) : (
        <Button variant="primary" isDisabled={!status} onClick={() => control("start")}>Start</Button>
      )}
    </div>
  );
}

export function AsteriskPage({ status, tab }: { status: Status | null; tab: string }) {
  const active = tab === "console" || tab === "settings" ? tab : "status";
  return (
    <>
      <PageSection className="asl-page-head">
        <Title headingLevel="h1">Asterisk</Title>
        <Content component="p">The Asterisk service that runs app_rpt and your nodes.</Content>
        <Tabs activeKey={active} onSelect={(_e, key) => go(`asterisk/${key}`)} className="asl-head-tabs">
          <Tab eventKey="status" title={<TabTitleText>Status</TabTitleText>} />
          <Tab eventKey="settings" title={<TabTitleText>Settings</TabTitleText>} />
          <Tab eventKey="console" title={<TabTitleText>Console</TabTitleText>} />
        </Tabs>
      </PageSection>
      <PageSection>
        {active === "settings" ? (
          <AsteriskSettings />
        ) : active === "console" ? (
          <Card>
            <CardTitle>Asterisk console</CardTitle>
            <CardBody>
              <Console status={status} />
            </CardBody>
          </Card>
        ) : (
          <Gallery hasGutter minWidths={{ default: "100%", xl: "36rem" }}>
            <Card>
              <CardTitle>Service</CardTitle>
              <CardBody>
                <DescriptionList isHorizontal isCompact>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Status</DescriptionListTerm>
                    <DescriptionListDescription>
                      <AsteriskState status={status} />
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Started</DescriptionListTerm>
                    <DescriptionListDescription>{status?.asterisk.since || "—"}</DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Running for</DescriptionListTerm>
                    <DescriptionListDescription>{duration(status?.asterisk.uptime)}</DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Version</DescriptionListTerm>
                    <DescriptionListDescription>{status?.versions.asterisk ?? "—"}</DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Service</DescriptionListTerm>
                    <DescriptionListDescription>
                      <code>asterisk.service</code>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>
              </CardBody>
              <CardFooter>
                <ServiceButtons status={status} />
              </CardFooter>
            </Card>
            <Card>
              <CardTitle>Registrations</CardTitle>
              <CardBody>
                {!status ? (
                  <Spinner size="md" aria-label="Loading" />
                ) : (
                  <>
                    <Registrations title="AllStarLink (HTTP)" regs={status.registrations} />
                    <Registrations title="IAX2" regs={status.iax_registrations} />
                  </>
                )}
              </CardBody>
            </Card>
          </Gallery>
        )}
      </PageSection>
    </>
  );
}
