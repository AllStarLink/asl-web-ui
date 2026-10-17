import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardTitle,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  ExpandableSection,
  FormSelect,
  FormSelectOption,
  Gallery,
  Label,
  PageSection,
  Spinner,
  Title,
} from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import CheckCircleIcon from "@patternfly/react-icons/dist/esm/icons/check-circle-icon";
import ExclamationTriangleIcon from "@patternfly/react-icons/dist/esm/icons/exclamation-triangle-icon";
import InfoCircleIcon from "@patternfly/react-icons/dist/esm/icons/info-circle-icon";
import TimesCircleIcon from "@patternfly/react-icons/dist/esm/icons/times-circle-icon";

import { get, message, post, Status } from "./api";
import { size, Started } from "./backupsApi";
import { useJob } from "./Job";
import { go } from "./useRoute";

export type AuthFinding = { id: string; level: "ok" | "info" | "warning" | "error"; message: string; data: Record<string, unknown> };
export type AuthSection = { id: string; node: string | null; complete: boolean; findings: AuthFinding[] };
export type Connectivity = {
  result: "ok" | "warning" | "error" | "aborted";
  counts: Record<string, number>;
  sections: AuthSection[];
  checked_at: number;
  duration: number;
  raw?: string;
};
type DiagnosticsData = {
  connectivity: Connectivity | null;
  nodelist: { installed: boolean; enabled: boolean; timer_active: boolean; last_result?: string };
  packages: { name: string; version: string }[];
};

// What to do about a problem, keyed on the check's finding id.
function hint(f: AuthFinding): string | null {
  if (f.level !== "error" && f.level !== "warning") return null;
  const d = f.data as Record<string, string>;
  switch (f.id) {
    case "config.missing_registration":
      return "Set the node's password on its General tab; that adds the registration.";
    case "config.missing_configuration":
      return "A registration line names a node that is not configured. On a new installation this is the sample line "
        + "for node 1234: set up your node and it is replaced. Otherwise remove the line in Manual Config Edit "
        + "(rpt_http_registrations.conf).";
    case "config.duplicate_registrations":
      return "Register each node one way only: keep the HTTP registration and comment out the register line in iax.conf.";
    case "config.no_registrations":
    case "config.no_nodes":
      return "Set up a public node with its AllStarLink password on the Nodes page.";
    case "public_ip.http_consensus":
    case "public_ip.iax_consensus":
      return "Different services see different addresses for this server. Your internet provider may use carrier-grade "
        + "NAT (CGNAT), which keeps other nodes from connecting. Ask the provider for a public IPv4 address.";
    case "node.registration_state":
      return "Check the node password on the node's General tab against the AllStarLink portal.";
    case "node.regserver_reachable":
      return "This server cannot reach register.allstarlink.org: check its internet connection and DNS.";
    case "node.udp_port":
      return `AllStarLink sees port ${d.registered_port ?? "?"}, but Asterisk listens on ${d.bindport ?? "?"}. That is `
        + "fine if your router forwards one to the other; the inbound connection test below tells.";
    case "node.inbound_reachability":
      return "Other nodes cannot connect: forward the IAX UDP port (Asterisk › Settings) on your router to this server, "
        + "and allow it in any firewall.";
    case "node.registered_recently":
      return "The node has not registered in the last 10 minutes: check the password and the internet connection.";
    case "public_ip.http_probe":
    case "public_ip.iax_probe":
      return "One test service did not answer; this is often temporary.";
    default:
      return null;
  }
}

function LevelIcon({ level }: { level: AuthFinding["level"] }) {
  if (level === "error") return <TimesCircleIcon className="asl-err" />;
  if (level === "warning") return <ExclamationTriangleIcon className="asl-warn" />;
  if (level === "ok") return <CheckCircleIcon className="asl-ok" />;
  return <InfoCircleIcon className="asl-info" />;
}

export function ResultLabel({ result }: { result: Connectivity["result"] }) {
  if (result === "ok") return <Label color="green" icon={<CheckCircleIcon />}>No problems</Label>;
  if (result === "warning") return <Label color="orange" icon={<ExclamationTriangleIcon />}>Warnings</Label>;
  if (result === "aborted") return <Label color="red" icon={<TimesCircleIcon />}>Could not complete</Label>;
  return <Label color="red" icon={<TimesCircleIcon />}>Problems found</Label>;
}

const SECTION_TITLES: Record<string, string> = { config: "Configuration", public_ip: "Public address" };

function ConnectivityResult({ c }: { c: Connectivity }) {
  return (
    <div className="asl-stack">
      {c.sections.filter((s) => s.findings.length > 0).map((s, i) => (
        <div key={i}>
          <Title headingLevel="h3" size="md" className="asl-subhead">
            {s.id === "node" ? `Node ${s.node}` : SECTION_TITLES[s.id] ?? s.id}
            {!s.complete && <span className="asl-sub"> · stopped early</span>}
          </Title>
          <ul className="asl-findings">
            {s.findings.filter((f) => !f.id.endsWith("_note") && f.id !== "node.summary").map((f, j) => (
              <li key={j}>
                <LevelIcon level={f.level} />
                <span>
                  {f.message}
                  {hint(f) && <span className="asl-sub asl-hint">{hint(f)}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {c.raw && (
        <ExpandableSection toggleText="Full output">
          <pre className="asl-job-log">{c.raw.trim()}</pre>
        </ExpandableSection>
      )}
    </div>
  );
}

type AsteriskLog =
  | { path: string; exists: false }
  | { path: string; exists: true; size: number; modified: number; lines: number; text: string; more: boolean };

const LINE_CHOICES = [100, 200, 500, 1000, 5000, 10000];

// Asterisk's messages.log: the last lines, newest at the bottom.
function LogLine({ line }: { line: string }) {
  const cls = /\] (ERROR|WARNING)\[/.exec(line)?.[1];
  return <span className={cls === "ERROR" ? "asl-log-error" : cls === "WARNING" ? "asl-log-warning" : undefined}>{line}{"\n"}</span>;
}

function AsteriskLogCard() {
  const [lines, setLines] = useState(200);
  const [log, setLog] = useState<AsteriskLog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pre = useRef<HTMLPreElement>(null);

  const load = useCallback(async (n: number) => {
    setBusy(true);
    try {
      setLog(await get<AsteriskLog>(`diagnostics/log?lines=${n}`));
      setError(null);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    void load(lines);
  }, [load, lines]);
  useLayoutEffect(() => {
    if (pre.current) pre.current.scrollTop = pre.current.scrollHeight;
  }, [log]);

  return (
    <Card>
      <CardTitle>Asterisk log</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <div className="asl-buttons">
            <span>Show the last</span>
            <FormSelect id="log-lines" aria-label="Number of lines" value={String(lines)} className="asl-log-lines"
                        onChange={(_e, v) => setLines(Number(v))}>
              {LINE_CHOICES.map((n) => (
                <FormSelectOption key={n} value={String(n)} label={`${n.toLocaleString()} lines`} />
              ))}
            </FormSelect>
            <Button variant="secondary" onClick={() => load(lines)} isLoading={busy} isDisabled={busy}>Refresh</Button>
            {log?.exists && (
              <Button variant="link" component="a" href="api/v1/diagnostics/log/download">
                Download the whole log ({size(log.size)})
              </Button>
            )}
          </div>
          {error && <Alert variant="danger" isInline title={error} />}
          {log && !log.exists && <Content component="p" className="asl-sub">{log.path} does not exist yet.</Content>}
          {log?.exists && (
            <>
              <pre ref={pre} className="asl-job-log asl-log" aria-label="Asterisk log">
                {log.text ? log.text.replace(/\n$/, "").split("\n").map((l, i) => <LogLine key={i} line={l} />)
                  : <span className="asl-sub">The log is empty.</span>}
              </pre>
              <Content component="p" className="asl-sub">
                <code>{log.path}</code>, last written {when(log.modified)}.
                {log.more ? ` Showing the last ${log.lines.toLocaleString()} lines.` : ""} Older entries are in the
                rotated files next to it (messages.log.1 …).
              </Content>
            </>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

export function when(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function Diagnostics({ status }: { status: Status | null }) {
  const [data, setData] = useState<DiagnosticsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [regserver, setRegserver] = useState<{ available: boolean; message: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const [nodelistMsg, setNodelistMsg] = useState<string | null>(null);
  const [jobElement, runJob] = useJob();

  const load = useCallback(async () => {
    try {
      setData(await get<DiagnosticsData>("diagnostics"));
    } catch (err) {
      setError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const connectivity = async () => {
    await runJob("Node connectivity check", () => post<Started>("diagnostics/connectivity", {}));
    await load();
  };
  const checkRegserver = async () => {
    setChecking(true);
    try {
      setRegserver(await post("diagnostics/registration-server", {}));
    } catch (err) {
      setRegserver({ available: false, message: message(err) });
    } finally {
      setChecking(false);
    }
  };
  const restartNodelist = async () => {
    setNodelistMsg(null);
    try {
      await post("diagnostics/nodelist/restart", {});
      setNodelistMsg("Restarted.");
      await load();
    } catch (err) {
      setNodelistMsg(message(err));
    }
  };

  const c = data?.connectivity;
  return (
    <>
      {jobElement}
      <PageSection className="asl-page-head">
        <Title headingLevel="h1">Diagnostics</Title>
        <Content component="p">Check that your nodes can register and be reached.</Content>
      </PageSection>
      <PageSection>
        {error && <Alert variant="danger" isInline title={error} />}
        {!data && !error && <Spinner aria-label="Loading" />}
        {data && (
          <div className="asl-stack">
            <Card>
              <CardTitle>Node connectivity check</CardTitle>
              <CardBody>
                <div className="asl-stack">
                  <Content component="p">
                    Checks the registration settings, the address the internet sees for this server, each public
                    node's registration and whether other nodes can connect in. It takes about 30 seconds.
                  </Content>
                  {c ? (
                    <>
                      <div className="asl-buttons">
                        <ResultLabel result={c.result} />
                        <span className="asl-sub">Last checked {when(c.checked_at)}</span>
                      </div>
                      <ConnectivityResult c={c} />
                    </>
                  ) : (
                    <Content component="p" className="asl-sub">Not checked yet.</Content>
                  )}
                </div>
              </CardBody>
              <CardFooter>
                <Button onClick={connectivity}>{c ? "Check again" : "Run the check"}</Button>
              </CardFooter>
            </Card>
            <Gallery hasGutter minWidths={{ default: "100%", lg: "28rem" }}>
              <Card>
                <CardTitle>Basic checks</CardTitle>
                <CardBody>
                  <DescriptionList isCompact>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Internet</DescriptionListTerm>
                      <DescriptionListDescription>
                        <Button variant="link" isInline onClick={() =>
                          runJob("Ping 8.8.8.8 (Google DNS)", () => post<Started>("diagnostics/ping", {}))}>
                          Ping 8.8.8.8
                        </Button>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>AllStarLink registration server</DescriptionListTerm>
                      <DescriptionListDescription>
                        <div className="asl-buttons">
                          <Button variant="link" isInline onClick={checkRegserver} isLoading={checking}>Check</Button>
                          {regserver && (
                            <Label color={regserver.available ? "green" : "red"}>{regserver.message}</Label>
                          )}
                        </div>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                    {data.nodelist.installed && (
                      <DescriptionListGroup>
                        <DescriptionListTerm>Node list service</DescriptionListTerm>
                        <DescriptionListDescription>
                          {!data.nodelist.enabled ? (
                            <div className="asl-buttons">
                              <Label color="green">Not enabled</Label>
                              <span className="asl-sub">Not needed unless a legacy application requires it.</span>
                            </div>
                          ) : (
                            <div className="asl-buttons">
                              {data.nodelist.timer_active ? (
                                <Label color="green">Running</Label>
                              ) : (
                                <Label color="orange">Not running</Label>
                              )}
                              <Button variant="link" isInline onClick={restartNodelist}>Restart</Button>
                              {nodelistMsg && <span className="asl-sub">{nodelistMsg}</span>}
                            </div>
                          )}
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                    )}
                    <DescriptionListGroup>
                      <DescriptionListTerm>Asterisk</DescriptionListTerm>
                      <DescriptionListDescription>
                        {status?.versions.asterisk ?? "—"}{" "}
                        <Button variant="link" isInline onClick={() => go("asterisk")}>Status and registrations</Button>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                  </DescriptionList>
                </CardBody>
              </Card>
              <Card>
                <CardTitle>Installed AllStarLink packages</CardTitle>
                <CardBody>
                  <Table aria-label="Packages" variant="compact">
                    <Thead>
                      <Tr>
                        <Th>Package</Th>
                        <Th>Version</Th>
                      </Tr>
                    </Thead>
                    <Tbody>
                      {data.packages.map((p) => (
                        <Tr key={p.name}>
                          <Td dataLabel="Package">{p.name}</Td>
                          <Td dataLabel="Version"><code>{p.version}</code></Td>
                        </Tr>
                      ))}
                    </Tbody>
                  </Table>
                </CardBody>
              </Card>
            </Gallery>
            <AsteriskLogCard />
          </div>
        )}
      </PageSection>
    </>
  );
}
