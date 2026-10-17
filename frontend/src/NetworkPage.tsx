import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  PageSection,
  Spinner,
  Title,
} from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import ExternalLinkAltIcon from "@patternfly/react-icons/dist/esm/icons/external-link-alt-icon";

import { message } from "./api";
import { cockpitUrl, FallbackAp, networkStatus, NetworkStatus, setFallbackAp } from "./networkApi";

// The host's active network connections, with links to Cockpit for changing
// them, and the ASL3 appliance's fallback access point.

function Addresses({ list }: { list: string[] }) {
  if (!list.length) return <span className="asl-sub">None</span>;
  return (
    <div>
      {list.map((a) => <div key={a}><code>{a}</code></div>)}
    </div>
  );
}

function CockpitLink({ path, children }: { path: string; children: string }) {
  return (
    <Button component="a" variant="secondary" href={cockpitUrl(path)} target="_blank" rel="noopener noreferrer"
      icon={<ExternalLinkAltIcon />} iconPosition="end">
      {children}
    </Button>
  );
}

function FallbackApAbout() {
  return (
    <>
      <Content component="p">
        When enabled, this server checks its network connection every minute. If it has none, it starts its own
        Wi-Fi network so that you can connect to it and set up Wi-Fi in Cockpit. The access point stops once the
        connection is back.
      </Content>
      <Alert variant="warning" isInline title="Not for mobile nodes">
        If this node is mobile and routinely drops off its network, for example on a phone hotspot in a vehicle, you
        likely do not want this enabled. Each time the connection drops, the Wi-Fi adapter switches to running the
        access point and does not join your other Wi-Fi networks while it is on.
      </Alert>
    </>
  );
}

function FallbackApUnavailable() {
  return (
    <Card>
      <CardTitle>Fallback access point</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <FallbackApAbout />
          <Alert variant="info" isInline title="The fallback access point needs the AllStarLink appliance to function">
            It is part of the asl3-appliance-pc and asl3-appliance-pi packages, and neither is installed.
          </Alert>
        </div>
      </CardBody>
    </Card>
  );
}

function FallbackApCard({ ap, onChanged }: { ap: Extract<FallbackAp, { available: true }>; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState<{ variant: "success" | "danger"; text: string } | null>(null);

  const change = async (enable: boolean) => {
    setConfirming(false);
    setBusy(true);
    setNotice(null);
    try {
      await setFallbackAp(enable);
      setNotice({ variant: "success", text: enable ? "The fallback AP is enabled." : "The fallback AP is disabled." });
      await onChanged();
    } catch (err) {
      setNotice({ variant: "danger", text: message(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardTitle>Fallback access point</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <FallbackApAbout />
          {notice && <Alert variant={notice.variant} isInline title={notice.text} />}
          <DescriptionList isHorizontal>
            <DescriptionListGroup>
              <DescriptionListTerm>Status</DescriptionListTerm>
              <DescriptionListDescription>
                <span className="asl-labels">
                  {ap.enabled ? <Label color="green">Enabled</Label> : <Label color="grey">Disabled</Label>}
                  {ap.active && <Label color="orange">Access point on now</Label>}
                </span>
              </DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Network name</DescriptionListTerm>
              <DescriptionListDescription>
                {ap.ssid ? <code>{ap.ssid}</code> : <span className="asl-warn">No Wi-Fi adapter found</span>}
                {ap.ssid && ap.open && <span className="asl-sub"> · open, no password</span>}
              </DescriptionListDescription>
            </DescriptionListGroup>
          </DescriptionList>
          <Content component="p" className="asl-sub">
            The network name, password and channel are set in <code>/etc/default/fallback-ap</code>.
          </Content>
          <div className="asl-buttons">
            {ap.enabled ? (
              <Button variant="secondary" isLoading={busy} isDisabled={busy}
                onClick={() => (ap.active ? setConfirming(true) : void change(false))}>
                Disable fallback AP
              </Button>
            ) : (
              <Button variant="primary" isLoading={busy} isDisabled={busy} onClick={() => void change(true)}>
                Enable fallback AP
              </Button>
            )}
          </div>
        </div>
      </CardBody>
      <Modal isOpen={confirming} onClose={() => setConfirming(false)} variant="small" aria-labelledby="ap-off-title">
        <ModalHeader title="Turn off the access point now?" labelId="ap-off-title" titleIconVariant="warning" />
        <ModalBody>
          The fallback access point is on. Disabling the feature also turns it off, so if you are connected through it,
          you lose this connection.
        </ModalBody>
        <ModalFooter>
          <Button variant="danger" onClick={() => void change(false)}>Disable fallback AP</Button>
          <Button variant="link" onClick={() => setConfirming(false)}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </Card>
  );
}

export function NetworkPage() {
  const [status, setStatus] = useState<NetworkStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await networkStatus());
      setLoadError(null);
    } catch (err) {
      setLoadError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const head = (
    <PageSection className="asl-page-head">
      <Title headingLevel="h1">Network</Title>
      <Content component="p" className="asl-sub">
        This server's active network connections. Change them in Cockpit.
      </Content>
    </PageSection>
  );
  if (loadError || !status) {
    return (
      <>
        {head}
        <PageSection>{loadError ? <Alert variant="danger" isInline title={loadError} /> : <Spinner aria-label="Loading" />}</PageSection>
      </>
    );
  }

  const ap = status.fallback_ap;
  return (
    <>
      {head}
      <PageSection>
        <div className="asl-stack">
          <Card>
            <CardTitle>Active connections</CardTitle>
            <CardBody>
              {status.interfaces.length ? (
                <Table aria-label="Active network interfaces" variant="compact">
                  <Thead>
                    <Tr>
                      <Th>Interface</Th>
                      <Th>Type</Th>
                      <Th>IPv4 addresses</Th>
                      <Th>IPv6 addresses</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {status.interfaces.map((i) => (
                      <Tr key={i.name}>
                        <Td dataLabel="Interface">
                          <strong>{i.name}</strong>
                          {i.mac && <div className="asl-sub">{i.mac}</div>}
                        </Td>
                        <Td dataLabel="Type">{i.type}</Td>
                        <Td dataLabel="IPv4 addresses"><Addresses list={i.ipv4} /></Td>
                        <Td dataLabel="IPv6 addresses"><Addresses list={i.ipv6} /></Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              ) : (
                <Alert variant="warning" isInline title="No active network connection">
                  No interface is up with an address other than a local or link-local one.
                </Alert>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardTitle>Change network settings</CardTitle>
            <CardBody>
              <div className="asl-stack">
                <Content component="p">
                  Addresses, DNS, Wi-Fi networks and other settings are managed in Cockpit, which opens in a new tab.
                  Log in there with the same account.
                </Content>
                <div className="asl-buttons">
                  <CockpitLink path="network">Network settings in Cockpit</CockpitLink>
                  <CockpitLink path="wifimanager">Wi-Fi Manager in Cockpit</CockpitLink>
                </div>
              </div>
            </CardBody>
          </Card>

          {ap.available ? <FallbackApCard ap={ap} onChanged={load} /> : <FallbackApUnavailable />}
        </div>
      </PageSection>
    </>
  );
}
