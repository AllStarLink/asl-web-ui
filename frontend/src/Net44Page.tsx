import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  AlertActionLink,
  Button,
  Card,
  CardBody,
  CardTitle,
  Checkbox,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Form,
  FormGroup,
  FormHelperText,
  HelperText,
  HelperTextItem,
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  PageSection,
  Radio,
  Spinner,
  Switch,
  Title,
} from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import ExternalLinkAltIcon from "@patternfly/react-icons/dist/esm/icons/external-link-alt-icon";

import { message } from "./api";
import { duration } from "./format";
import {
  checkNet44, configureNet44, confirmNet44, migrateNet44, Net44Check, Net44Mode, Net44Ready, net44Status,
  Net44Status, removeNet44, setNet44Mode, setNet44Zone, startNet44, stopNet44,
} from "./net44Api";
import { PlainTextArea, PlainTextInput } from "./PlainInput";
import { useReauth } from "./Reauth";

// 44Net Connect: a public 44Net address for inbound AllStarLink calls,
// through a WireGuard tunnel run by NetworkManager behind its own firewalld
// zone. Firewall first, then the tunnel's configuration, then starting it
// (stopped again unless confirmed), then the checks from the documentation.

const DOC = "https://allstarlink.github.io/adv-topics/44net-connect/";
const PORTAL = "https://portal.ampr.org/";

type Notice = { variant: "success" | "danger" | "warning" | "info"; text: string; notes?: string[] };

function bytes(n: number | null): string {
  if (n === null) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function ModeChoice({ mode, onChange, name }: { mode: Net44Mode; onChange: (m: Net44Mode) => void; name: string }) {
  return (
    <>
      <Radio id={`${name}-full`} name={name} isChecked={mode === "full"} onChange={() => onChange("full")}
        label="Full tunnel (recommended)"
        description="All of this server's internet traffic goes through the tunnel, as the 44Net portal sets it up." />
      <Radio id={`${name}-split`} name={name} isChecked={mode === "split"} onChange={() => onChange("split")}
        label="AllStarLink traffic only (advanced)"
        description={"Only traffic to the AllStarLink servers and replies to calls to the 44Net address go through " +
          "the tunnel; everything else keeps using the local connection. The servers' addresses are looked up " +
          "again every few hours."} />
    </>
  );
}

function ZoneCard({ s, onDone }: { s: Net44Ready; onDone: (n: Notice, next?: Net44Ready) => void }) {
  const [echolink, setEcholink] = useState(s.selection.echolink);
  const [rtcm, setRtcm] = useState(s.selection.rtcm);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setEcholink(s.selection.echolink);
    setRtcm(s.selection.rtcm);
  }, [s.selection.echolink, s.selection.rtcm]);

  const save = async () => {
    setBusy(true);
    try {
      const next = await setNet44Zone(echolink, rtcm);
      onDone({ variant: "success", text: `The firewall zone ${s.zone_name} is set up.` }, next);
    } catch (err) {
      onDone({ variant: "danger", text: message(err) });
    } finally {
      setBusy(false);
    }
  };

  const changed = echolink !== s.selection.echolink || rtcm !== s.selection.rtcm;
  const iaxService = s.asterisk.iax_port >= 4560 && s.asterisk.iax_port <= 4580;
  return (
    <Card>
      <CardTitle>1. Firewall</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <Content component="p">
            The tunnel gives this node a public address that anyone on the internet can reach. The firewall
            zone <code>{s.zone_name}</code> decides what they can reach there, so it is set up before the tunnel.
            Management (SSH, Cockpit, these web pages, AMI) is never opened on the 44Net address: to manage the node
            from elsewhere, use a private VPN such as Tailscale.
          </Content>
          <DescriptionList isHorizontal>
            <DescriptionListGroup>
              <DescriptionListTerm>Zone</DescriptionListTerm>
              <DescriptionListDescription>
                {!s.zone ? <Label color="grey">Not set up</Label>
                  : s.zone_current ? <Label color="green">Set up</Label>
                  : <Label color="orange">Out of date</Label>}
                {s.zone && (
                  <span className="asl-sub">
                    {" "}opens {[...s.zone.services, ...s.zone.ports].join(", ") || "nothing"}
                  </span>
                )}
              </DescriptionListDescription>
            </DescriptionListGroup>
          </DescriptionList>
          {s.zone && !s.zone_current && (
            <Alert variant="warning" isInline title="The zone does not match the node's settings">
              It should open {[...s.expected_zone.services, ...s.expected_zone.ports].join(", ")}. Updating it closes
              everything else.
            </Alert>
          )}
          <div className="asl-stack">
            <Switch id="net44-iax" label={`IAX2: AllStarLink calls (UDP port ${s.asterisk.iax_port}${iaxService ? "" : ", by number"})`}
              isChecked isDisabled />
            <Switch id="net44-echolink" label="EchoLink (UDP ports 5198–5199)" isChecked={echolink}
              onChange={(_e, v) => setEcholink(v)} />
            {!s.asterisk.echolink && echolink && (
              <HelperText><HelperTextItem variant="warning">EchoLink (chan_echolink) is not loaded.</HelperTextItem></HelperText>
            )}
            <Switch id="net44-rtcm"
              label={s.asterisk.voter_port !== null ? `VOTER/RTCM receivers (UDP port ${s.asterisk.voter_port})`
                : "VOTER/RTCM receivers (chan_voter is not loaded)"}
              isChecked={rtcm} isDisabled={s.asterisk.voter_port === null} onChange={(_e, v) => setRtcm(v)} />
          </div>
          <div className="asl-buttons">
            <Button variant={s.zone ? "secondary" : "primary"} isLoading={busy}
              isDisabled={busy || (!!s.zone && s.zone_current && !changed)} onClick={() => void save()}>
              {s.zone ? "Update firewall zone" : "Create firewall zone"}
            </Button>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

function SetupForm({ s, replacing, onDone, onCancel }: {
  s: Net44Ready; replacing: boolean; onDone: (n: Notice, next?: Net44Ready) => void; onCancel?: () => void;
}) {
  const [config, setConfig] = useState("");
  const [key, setKey] = useState("");
  const [mode, setMode] = useState<Net44Mode>(s.connection?.mode ?? "full");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const placeholder = config.includes("REPLACE_WITH_YOUR_PRIVATE_KEY");

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await configureNet44(config, key, mode);
      setConfig("");
      setKey("");
      onDone({ variant: "success", text: "The tunnel is set up. Start it below.", notes: res.notes }, res.status);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Form onSubmit={(e) => { e.preventDefault(); void save(); }}>
      {!s.zone && <Alert variant="info" isInline title="Set up the firewall zone first (step 1)." />}
      {error && <Alert variant="danger" isInline title={error} />}
      <FormGroup label="WireGuard configuration" fieldId="net44-config" isRequired>
        <PlainTextArea id="net44-config" value={config} onChange={(_e, v) => setConfig(v)} rows={12}
          className="asl-mono" resizeOrientation="vertical" isDisabled={!s.zone}
          placeholder={"[Interface]\nPrivateKey = REPLACE_WITH_YOUR_PRIVATE_KEY\nAddress = 44.x.x.x/32\n…\n\n[Peer]\n…"} />
        <FormHelperText>
          <HelperText>
            <HelperTextItem>
              The configuration the <a href={PORTAL} target="_blank" rel="noopener noreferrer">44Net portal</a> shows
              for your 44Net Connect tunnel. DNS servers and IPv6 settings in it are not used.
            </HelperTextItem>
          </HelperText>
        </FormHelperText>
      </FormGroup>
      <FormGroup label="Private key" fieldId="net44-key" isRequired={placeholder}>
        <PlainTextInput id="net44-key" type="password" autoComplete="off" value={key} onChange={(_e, v) => setKey(v)}
          isDisabled={!s.zone} />
        <FormHelperText>
          <HelperText>
            <HelperTextItem>
              The portal shows it once, when the tunnel is created. Leave this empty if the configuration above already
              contains it. It is kept only in NetworkManager's settings: never shown again, and never in backups.
            </HelperTextItem>
          </HelperText>
        </FormHelperText>
      </FormGroup>
      <FormGroup label="Routing" role="radiogroup" fieldId="net44-mode" isStack>
        <ModeChoice mode={mode} onChange={setMode} name="net44-setup-mode" />
      </FormGroup>
      <div className="asl-buttons">
        <Button type="submit" isLoading={busy} isDisabled={busy || !s.zone || !config.trim() || (placeholder && !key.trim())}>
          {replacing ? "Replace tunnel configuration" : "Save tunnel configuration"}
        </Button>
        {onCancel && <Button variant="link" onClick={onCancel}>Cancel</Button>}
      </div>
    </Form>
  );
}

function TunnelSettings({ s, onDone }: { s: Net44Ready; onDone: (n: Notice, next?: Net44Ready) => void }) {
  const c = s.connection!;
  const [replacing, setReplacing] = useState(false);
  const [mode, setMode] = useState<Net44Mode>(c.mode);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [deleteZone, setDeleteZone] = useState(false);
  const [reauthElement, withReauth] = useReauth();
  const running = c.state !== null;
  useEffect(() => setMode(c.mode), [c.mode]);

  const applyMode = async () => {
    setBusy(true);
    try {
      const next = await setNet44Mode(mode);
      onDone({ variant: "success", text: running ? "The tunnel restarted with the new routing. Confirm it above."
        : "The routing is changed." }, next);
    } catch (err) {
      onDone({ variant: "danger", text: message(err) });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setRemoving(false);
    try {
      const next = await withReauth(() => removeNet44(deleteZone));
      if (next) onDone({ variant: "success", text: "44Net Connect is removed." }, next);
    } catch (err) {
      onDone({ variant: "danger", text: message(err) });
    }
  };

  if (replacing) {
    return (
      <SetupForm s={s} replacing onCancel={() => setReplacing(false)}
        onDone={(n, next) => { if (next) setReplacing(false); onDone(n, next); }} />
    );
  }
  return (
    <div className="asl-stack">
      <DescriptionList isHorizontal>
        <DescriptionListGroup>
          <DescriptionListTerm>44Net address</DescriptionListTerm>
          <DescriptionListDescription><code>{c.address ?? "—"}</code> on <code>{c.interface}</code></DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Server</DescriptionListTerm>
          <DescriptionListDescription>
            <code>{c.endpoint ?? "—"}</code>
            {c.keepalive && <span className="asl-sub"> · keepalive every {c.keepalive} s</span>}
            {c.mtu && <span className="asl-sub"> · MTU {c.mtu}</span>}
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Public key</DescriptionListTerm>
          <DescriptionListDescription>
            <code className="asl-filename">{c.public_key ?? "—"}</code>
            <div className="asl-sub">The portal shows the same key for your tunnel.</div>
          </DescriptionListDescription>
        </DescriptionListGroup>
        {c.mode === "split" && (
          <DescriptionListGroup>
            <DescriptionListTerm>Through the tunnel</DescriptionListTerm>
            <DescriptionListDescription>
              {c.routes.length ? c.routes.map((r) => <div key={r}><code>{r}</code></div>) : "—"}
              <div className="asl-sub">and replies from the 44Net address</div>
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
      </DescriptionList>
      <Form>
        <FormGroup label="Routing" role="radiogroup" fieldId="net44-routing" isStack>
          <ModeChoice mode={mode} onChange={setMode} name="net44-mode" />
        </FormGroup>
      </Form>
      {mode !== c.mode && running && (
        <Alert variant="info" isInline isPlain title="The tunnel restarts with the new routing; confirm it again afterwards." />
      )}
      <div className="asl-buttons">
        <Button variant="secondary" isLoading={busy} isDisabled={busy || mode === c.mode} onClick={() => void applyMode()}>
          Change routing
        </Button>
        <Button variant="secondary" isDisabled={running} onClick={() => setReplacing(true)}>
          Replace configuration
        </Button>
        <Button variant="danger" onClick={() => setRemoving(true)}>Remove…</Button>
      </div>
      {running && <Content component="p" className="asl-sub">Stop the tunnel to replace its configuration.</Content>}
      <Modal isOpen={removing} onClose={() => setRemoving(false)} variant="small" aria-labelledby="net44-remove-title">
        <ModalHeader title="Remove 44Net Connect?" labelId="net44-remove-title" titleIconVariant="warning" />
        <ModalBody>
          <div className="asl-stack">
            <p>
              The tunnel stops and its configuration, with the private key, is deleted. To set it up again, you need
              the configuration and private key from the 44Net portal.
            </p>
            <Checkbox id="net44-remove-zone" label={`Also delete the firewall zone ${s.zone_name}`} isChecked={deleteZone}
              onChange={(_e, v) => setDeleteZone(v)} />
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="danger" onClick={() => void remove()}>Remove</Button>
          <Button variant="link" onClick={() => setRemoving(false)}>Cancel</Button>
        </ModalFooter>
      </Modal>
      {reauthElement}
    </div>
  );
}

function TunnelCard({ s, onDone }: { s: Net44Ready; onDone: (n: Notice, next?: Net44Ready) => void }) {
  const c = s.connection!;
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(false);
  const pending = s.checkpoint !== null && "seconds_left" in s.checkpoint;

  const act = async (work: () => Promise<Net44Ready>, done: string) => {
    setStarting(false);
    setBusy(true);
    try {
      onDone({ variant: "success", text: done }, await work());
    } catch (err) {
      onDone({ variant: "danger", text: message(err) });
    } finally {
      setBusy(false);
    }
  };

  const t = c.tunnel;
  const handshakeAge = t?.latest_handshake ? t.now - t.latest_handshake : null;
  return (
    <Card>
      <CardTitle>3. Tunnel</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <DescriptionList isHorizontal>
            <DescriptionListGroup>
              <DescriptionListTerm>Status</DescriptionListTerm>
              <DescriptionListDescription>
                <span className="asl-labels">
                  {c.state === "activated" ? <Label color="green">Running</Label>
                    : c.state ? <Label color="blue">{c.state}</Label> : <Label color="grey">Stopped</Label>}
                  {c.state && pending && <Label color="orange">Waiting for confirmation</Label>}
                  {!pending && c.autoconnect && <Label color="grey">Starts at boot</Label>}
                </span>
              </DescriptionListDescription>
            </DescriptionListGroup>
            {t && (
              <>
                <DescriptionListGroup>
                  <DescriptionListTerm>Last handshake</DescriptionListTerm>
                  <DescriptionListDescription>
                    {handshakeAge === null ? <span className="asl-warn">None yet</span>
                      : handshakeAge > 180 ? <span className="asl-warn">{duration(handshakeAge)} ago</span>
                      : `${duration(handshakeAge)} ago`}
                    {handshakeAge === null && (
                      <div className="asl-sub">
                        Without a handshake the 44Net server has not accepted the tunnel: check the private key.
                      </div>
                    )}
                  </DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>Traffic</DescriptionListTerm>
                  <DescriptionListDescription>{bytes(t.rx_bytes)} received · {bytes(t.tx_bytes)} sent</DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>Firewall zone</DescriptionListTerm>
                  <DescriptionListDescription>
                    {c.active_zone === s.zone_name ? <code>{c.active_zone}</code>
                      : <span className="asl-err">{c.active_zone ?? "none"}</span>}
                  </DescriptionListDescription>
                </DescriptionListGroup>
              </>
            )}
          </DescriptionList>
          <div className="asl-buttons">
            {c.state ? (
              <Button variant="secondary" isLoading={busy} isDisabled={busy}
                onClick={() => void act(stopNet44, "The tunnel is stopped and no longer starts at boot.")}>
                Stop tunnel
              </Button>
            ) : (
              <Button variant="primary" isLoading={busy} isDisabled={busy || !s.zone} onClick={() => setStarting(true)}>
                Start tunnel
              </Button>
            )}
          </div>
        </div>
      </CardBody>
      <Modal isOpen={starting} onClose={() => setStarting(false)} variant="small" aria-labelledby="net44-start-title">
        <ModalHeader title="Start the tunnel?" labelId="net44-start-title" />
        <ModalBody>
          <div className="asl-stack">
            {c.mode === "full" && (
              <p>
                All of this server's internet traffic will go through the tunnel. If you reach this page from outside
                the local network, the connection to it may drop.
              </p>
            )}
            <p>
              Once it is up, confirm that this page still works. If nobody confirms within 2 minutes, the tunnel stops
              by itself. Only a confirmed tunnel starts again at boot.
            </p>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button onClick={() => void act(startNet44, "The tunnel is up. Confirm it to keep it running.")}>Start</Button>
          <Button variant="link" onClick={() => setStarting(false)}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </Card>
  );
}

function CheckCard() {
  const [result, setResult] = useState<Net44Check | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await checkNet44());
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  const yes = (ok: boolean) => (ok ? <Label color="green">44Net</Label> : <Label color="orange">Not 44Net</Label>);
  return (
    <Card>
      <CardTitle>4. Check</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <Content component="p">
            With the tunnel running, the internet and the AllStarLink servers should see this node at its 44Net
            address. The registration shows it after the next refresh, about two minutes after the tunnel starts.
          </Content>
          {error && <Alert variant="danger" isInline title={error} />}
          {result && (
            <>
              <DescriptionList isHorizontal>
                <DescriptionListGroup>
                  <DescriptionListTerm>Address the internet sees</DescriptionListTerm>
                  <DescriptionListDescription>
                    {result.public_ip ? <><code>{result.public_ip}</code> {yes(result.public_ip_on_44net)}</>
                      : <span className="asl-warn">{result.public_ip_error}</span>}
                  </DescriptionListDescription>
                </DescriptionListGroup>
              </DescriptionList>
              {result.registrations_error ? <Alert variant="warning" isInline title={result.registrations_error} />
                : result.registrations.length > 0 && (
                <Table aria-label="Registrations" variant="compact">
                  <Thead>
                    <Tr><Th>Node</Th><Th>Address AllStarLink sees</Th><Th>State</Th></Tr>
                  </Thead>
                  <Tbody>
                    {result.registrations.map((r) => (
                      <Tr key={r.node}>
                        <Td dataLabel="Node">{r.node}</Td>
                        <Td dataLabel="Address AllStarLink sees"><code>{r.perceived}</code> {yes(r.on_44net)}</Td>
                        <Td dataLabel="State">{r.state}</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              )}
            </>
          )}
          <div className="asl-buttons">
            <Button variant="secondary" isLoading={busy} isDisabled={busy} onClick={() => void run()}>Run checks</Button>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

export function Net44Page() {
  const [status, setStatus] = useState<Net44Status | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [left, setLeft] = useState<number | null>(null);
  const [migrating, setMigrating] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await net44Status());
      setLoadError(null);
    } catch (err) {
      setLoadError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const s = status?.available ? status : null;
  const pending = s?.checkpoint && "seconds_left" in s.checkpoint ? s.checkpoint.seconds_left : null;
  const running = s?.connection?.state ?? null;

  // While a start waits for confirmation, count down and look again often;
  // while the tunnel runs, refresh its handshake now and then.
  useEffect(() => {
    setLeft(pending);
    if (pending === null && !running) return;
    const tick = setInterval(() => setLeft((n) => (n === null ? n : Math.max(0, n - 1))), 1000);
    const poll = setInterval(() => void load(), pending !== null ? 5000 : 20000);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, [pending, running, load]);

  const done = (n: Notice, next?: Net44Ready) => {
    setNotice(n);
    if (next) setStatus(next);
    else void load();
  };

  const act = async (work: () => Promise<Net44Ready>, text: string) => {
    try {
      done({ variant: "success", text }, await work());
    } catch (err) {
      done({ variant: "danger", text: message(err) });
    }
  };

  const migrate = async () => {
    setMigrating(false);
    try {
      const res = await migrateNet44();
      done({ variant: "success", text: "The tunnel is now run by NetworkManager. Start it below.", notes: res.notes },
        res.status);
    } catch (err) {
      done({ variant: "danger", text: message(err) });
    }
  };

  const head = (
    <PageSection className="asl-page-head">
      <Title headingLevel="h1">44Net Connect</Title>
      <Content component="p" className="asl-sub">
        A public 44Net (AMPRNet) address for this node through a WireGuard tunnel, so that other nodes can call it
        even behind NAT, CGNAT or a router you cannot forward ports on.{" "}
        <a href={DOC} target="_blank" rel="noopener noreferrer">About 44Net Connect <ExternalLinkAltIcon /></a>
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
  if (!status.available) {
    return (
      <>
        {head}
        <PageSection>
          <Alert variant="info" isInline title="44Net Connect needs the AllStarLink appliance to function">
            {status.message}
          </Alert>
        </PageSection>
      </>
    );
  }

  const st = status;
  const c = st.connection;
  const legacy = st.legacy;
  return (
    <>
      {head}
      <PageSection>
        <div className="asl-stack">
          {pending !== null && (
            <Alert variant="warning" isInline title="Keep the 44Net Connect tunnel running?"
              actionLinks={
                <>
                  <AlertActionLink onClick={() => void act(confirmNet44, "The tunnel keeps running and starts at boot.")}>
                    Keep it running
                  </AlertActionLink>
                  <AlertActionLink onClick={() => void act(stopNet44, "The tunnel is stopped.")}>Stop it now</AlertActionLink>
                </>
              }>
              The tunnel is up and this page still reaches the server. Unless you keep it, it stops by itself in{" "}
              {left ?? pending} seconds.
            </Alert>
          )}
          {st.checkpoint && "rolled_back" in st.checkpoint && (
            <Alert variant="warning" isInline title="The tunnel was stopped: its start was not confirmed in time">
              If this page lost its connection when the tunnel started, open it from the local network, or choose
              AllStarLink traffic only.
            </Alert>
          )}
          {notice && (
            <Alert variant={notice.variant} isInline title={notice.text}>
              {notice.notes && notice.notes.length > 0 && <ul>{notice.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
            </Alert>
          )}
          {st.issues.map((i) => <Alert key={i} variant="danger" isInline title={i} />)}

          {legacy?.config && !c && (
            <Card>
              <CardTitle>Tunnel set up by hand</CardTitle>
              <CardBody>
                <div className="asl-stack">
                  <Content component="p">
                    This server has a tunnel set up with <code>wg-quick</code>, following the documentation:{" "}
                    <code>{legacy.config}</code>, run by <code>{legacy.unit}</code>
                    {legacy.active ? " (running)" : legacy.enabled ? " (starts at boot)" : " (not used)"}
                    {legacy.zone && <> and bound to the firewall zone <code>{legacy.zone}</code></>}.
                  </Content>
                  <Content component="p">
                    Migrating copies its configuration to NetworkManager, disables <code>{legacy.unit}</code>
                    {legacy.zone && <> and removes <code>{legacy.interface}</code>'s zone binding</>}. The file stays
                    where it is. You start the tunnel here afterwards.
                  </Content>
                  {!st.zone && <Alert variant="info" isInline title="Set up the firewall zone first (step 1)." />}
                  <div className="asl-buttons">
                    <Button isDisabled={!st.zone} onClick={() => setMigrating(true)}>Migrate this tunnel</Button>
                  </div>
                </div>
              </CardBody>
            </Card>
          )}

          <ZoneCard s={st} onDone={done} />

          <Card>
            <CardTitle>2. Tunnel configuration</CardTitle>
            <CardBody>
              {c ? <TunnelSettings s={st} onDone={done} /> : <SetupForm s={st} replacing={false} onDone={done} />}
            </CardBody>
          </Card>

          {c && <TunnelCard s={st} onDone={done} />}
          {c && <CheckCard />}
        </div>
      </PageSection>
      <Modal isOpen={migrating} onClose={() => setMigrating(false)} variant="small" aria-labelledby="net44-migrate-title">
        <ModalHeader title="Migrate the hand-made tunnel?" labelId="net44-migrate-title" />
        <ModalBody>
          {legacy?.active ? `${legacy.unit} is running: it stops now. ` : ""}
          The new tunnel does not start until you start it here.
        </ModalBody>
        <ModalFooter>
          <Button onClick={() => void migrate()}>Migrate</Button>
          <Button variant="link" onClick={() => setMigrating(false)}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </>
  );
}
