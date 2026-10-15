import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  ActionGroup,
  Alert,
  Breadcrumb,
  BreadcrumbItem,
  Button,
  Card,
  CardBody,
  CardTitle,
  Checkbox,
  Content,
  Form,
  FormGroup,
  FormHelperText,
  FormSelect,
  FormSelectOption,
  HelperText,
  HelperTextItem,
  Label,
  PageSection,
  Radio,
  Spinner,
  Switch,
  Tab,
  Tabs,
  TabTitleText,
  Title,
  ToggleGroup,
  ToggleGroupItem,
} from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";

import { PlainTextInput } from "./PlainInput";
import { ApiError, message, Status } from "./api";
import { useChange } from "./ChangeReview";
import { numberProblem } from "./NodeWizard";
import {
  AccessLists, addAccess, clearAccess, getAccess, getNode, INTERFACE_NAMES, NodeDetail, NodeList, removeAccess,
} from "./nodesApi";
import { useNodeList } from "./Nodes";
import { TuningPanel } from "./Tuning";
import { RegistrationLabel } from "./Overview";
import { go, useLeaveGuard } from "./useRoute";

// The General, Radio interface and Customizations tabs edit one draft of the
// node's settings. It survives switching tabs, and is reviewed and saved (or
// discarded) as one change. Tuning and access lists take effect immediately.
type Draft = {
  number: string;
  password: string;
  callsign: string;
  replaceId: boolean;
  duplex: string;
  l2l: string;
  statpost: boolean;
  linkOn: boolean;
  target: string;
  linkMode: "transceive" | "monitor";
  permanent: boolean;
  replaceMacro: boolean;
  iface: string;
  custom: string[];
};
type SetDraft = (change: Partial<Draft>) => void;
type Problems = Partial<Record<keyof Draft, string>>;
type Op = { op: string; node: string; [key: string]: unknown };

function initial(node: NodeDetail): Draft {
  const st = node.startup;
  return {
    number: node.number, password: "", callsign: node.callsign ?? "", replaceId: false,
    duplex: String(node.duplex ?? 2), l2l: node.linktolink, statpost: node.statpost,
    linkOn: st.target !== null || st.custom, target: st.target ?? "", linkMode: st.mode ?? "transceive",
    permanent: st.permanent, replaceMacro: false,
    iface: node.interface ?? "SimpleUSB", custom: node.customizations.selected,
  };
}

const sameSet = (a: string[], b: string[]) => [...a].sort().join() === [...b].sort().join();

// The draft's differences from the node, as plan operations (with the tab
// each belongs to), and what is wrong with the fields that changed.
function changes(node: NodeDetail, list: NodeList, d: Draft): { ops: (Op & { tab: string })[]; problems: Problems } {
  const ops: (Op & { tab: string })[] = [];
  const problems: Problems = {};
  const n = node.number;
  const base = initial(node);
  const add = (tab: string, op: string, params: Record<string, unknown> = {}) => ops.push({ tab, op, node: n, ...params });

  if (d.callsign.trim().toUpperCase() !== (node.callsign ?? "")) {
    if (!/^[0-9A-Za-z/-]{3,}$/.test(d.callsign.trim())) {
      problems.callsign = "Letters, numbers, / and -, at least 3 characters.";
    } else if (!node.id_simple && !d.replaceId) {
      problems.replaceId = "Tick this to replace the custom ID.";
    }
    add("general", "callsign", { callsign: d.callsign, replace_custom: d.replaceId });
  }
  if (d.password) {
    if (!/^[0-9a-zA-Z_-]{6,}$/.test(d.password)) problems.password = "At least 6 letters, numbers, _ or -.";
    add("general", "password", { password: d.password });
  }
  if (d.duplex !== base.duplex || (d.duplex === "0" && d.l2l !== base.l2l)) {
    add("general", "duplex", { duplex: Number(d.duplex), linktolink: d.duplex === "0" ? d.l2l : undefined });
  }
  if (d.statpost !== base.statpost) add("general", "statpost", { enabled: d.statpost });
  const st = node.startup;
  if (d.linkOn !== base.linkOn || (d.linkOn && (d.target.trim() !== base.target || d.linkMode !== base.linkMode ||
                                                d.permanent !== base.permanent))) {
    if (d.linkOn && !/^[0-9]{4,7}$/.test(d.target.trim())) problems.target = "Enter the node number to connect to.";
    if (st.custom && !d.replaceMacro) problems.replaceMacro = "Tick this to replace the custom startup macro.";
    if (d.linkOn && d.permanent && !st.permanent_available) add("general", "permanent_links");
    add("general", "startup_link", {
      target: d.linkOn ? d.target.trim() : null, mode: d.linkMode, permanent: d.linkOn && d.permanent,
      replace_custom: d.replaceMacro,
    });
  }
  if (d.iface !== base.iface) add("interface", "interface", { interface: d.iface });
  if (!sameSet(d.custom, base.custom)) add("customizations", "customize", { names: d.custom });
  if (d.number !== n) {
    const problem = numberProblem(d.number, list.nodes.map((x) => x.number), n);
    if (problem) problems.number = problem;
    add("general", "rename", { number: d.number });
  }
  return { ops, problems };
}

function Help({ problem, hint }: { problem?: string; hint?: ReactNode }) {
  if (!problem && !hint) return null;
  return (
    <FormHelperText>
      <HelperText>
        <HelperTextItem variant={problem ? "error" : "default"}>{problem ?? hint}</HelperTextItem>
      </HelperText>
    </FormHelperText>
  );
}

function General({ node, list, status, draft, set, problems }: {
  node: NodeDetail; list: NodeList; status: Status | null; draft: Draft; set: SetDraft; problems: Problems;
}) {
  const running = status?.nodes.find((n) => n.node === node.number);
  const st = node.startup;
  return (
    <Card>
      <CardTitle>General</CardTitle>
      <CardBody>
        <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
          <FormGroup label="Registration" fieldId="node-registration">
            <div id="node-registration">
              {node.private ? <Label>Private node, not registered</Label>
                : running ? <RegistrationLabel node={running} />
                : node.registered ? <Label color="blue">Configured</Label> : <Label color="orange">Not configured</Label>}
            </div>
          </FormGroup>
          <FormGroup label="Node number" fieldId="node-number">
            <PlainTextInput id="node-number" value={draft.number} onChange={(_e, v) => set({ number: v.trim() })}
                            validated={problems.number ? "error" : "default"} inputMode="numeric" autoComplete="off" />
            <Help problem={problems.number} hint={draft.number !== node.number &&
              "Renames the node everywhere: its settings, registration, radio interface and access list."} />
          </FormGroup>
          {!node.private && (
            <FormGroup label="Node password" fieldId="node-password">
              <PlainTextInput id="node-password" type="password" value={draft.password} autoComplete="new-password"
                              placeholder={node.password_set ? "Unchanged" : "Not set"}
                              validated={problems.password ? "error" : "default"}
                              onChange={(_e, v) => set({ password: v })} />
              <Help problem={problems.password} hint="From allstarlink.org: Portal, Node Settings." />
            </FormGroup>
          )}
          <FormGroup label="Call sign" fieldId="node-callsign">
            <PlainTextInput id="node-callsign" value={draft.callsign} onChange={(_e, v) => set({ callsign: v.toUpperCase() })}
                            validated={problems.callsign ? "error" : "default"} autoComplete="off" />
            <Help problem={problems.callsign} hint={!node.id_simple && <>Custom ID: <code>{node.idrecording}</code></>} />
            {!node.id_simple && draft.callsign.trim() !== "" && (
              <>
                <Checkbox id="node-replace-id" isChecked={draft.replaceId} onChange={(_e, v) => set({ replaceId: v })}
                          label={`Replace the custom ID (${node.idrecording}) with the call sign`} />
                <Help problem={problems.replaceId} />
              </>
            )}
          </FormGroup>
          <FormGroup label="Duplex" fieldId="node-duplex">
            <FormSelect id="node-duplex" value={draft.duplex} onChange={(_e, v) => set({ duplex: v })}>
              {list.duplex.map((d) => <FormSelectOption key={d.value} value={String(d.value)} label={`${d.value}: ${d.label}`} />)}
            </FormSelect>
          </FormGroup>
          {draft.duplex === "0" && (
            <FormGroup role="radiogroup" fieldId="node-l2l" label="With no telemetry, use" isInline>
              <Radio id="l2l-no" name="l2l" label="Half duplex" isChecked={draft.l2l !== "yes"} onChange={() => set({ l2l: "no" })} />
              <Radio id="l2l-yes" name="l2l" label="Full duplex (for an external repeater controller)"
                     isChecked={draft.l2l === "yes"} onChange={() => set({ l2l: "yes" })} />
            </FormGroup>
          )}
          <FormGroup role="radiogroup" fieldId="startup-on" label="Connect at startup" isStack>
            {st.custom && <Content component="p">Custom startup macro: <code>{st.macro}</code></Content>}
            <Radio id="startup-off" name="startup-on" label="Don't connect to another node" isChecked={!draft.linkOn}
                   onChange={() => set({ linkOn: false })} />
            <Radio id="startup-yes" name="startup-on" label="Connect to a node when Asterisk starts"
                   isChecked={draft.linkOn} onChange={() => set({ linkOn: true })} />
          </FormGroup>
          {draft.linkOn && (
            <>
              <FormGroup label="Node to connect to" fieldId="startup-target">
                <PlainTextInput id="startup-target" value={draft.target} onChange={(_e, v) => set({ target: v })}
                                validated={problems.target ? "error" : "default"} inputMode="numeric" autoComplete="off" />
                <Help problem={problems.target} />
              </FormGroup>
              <FormGroup role="radiogroup" fieldId="startup-mode" label="Link" isInline>
                <Radio id="startup-tx" name="startup-mode" label="Transceive" isChecked={draft.linkMode === "transceive"}
                       onChange={() => set({ linkMode: "transceive" })} />
                <Radio id="startup-mon" name="startup-mode" label="Monitor only" isChecked={draft.linkMode === "monitor"}
                       onChange={() => set({ linkMode: "monitor" })} />
              </FormGroup>
              <FormGroup fieldId="startup-permanent">
                <Checkbox id="startup-permanent" label="Keep the link up (reconnect if it drops)" isChecked={draft.permanent}
                          onChange={(_e, v) => set({ permanent: v })}
                          description={st.permanent_available
                            ? "Uses the permanent link DTMF commands in the node's function table."
                            : `Enables the permanent link DTMF commands (${st.funcchar}811, ${st.funcchar}812, ` +
                              `${st.funcchar}813) by adding them to the node's function table; they are commented ` +
                              "out in the stock rpt.conf."} />
              </FormGroup>
            </>
          )}
          {st.custom && (
            <FormGroup fieldId="startup-replace">
              <Checkbox id="startup-replace" isChecked={draft.replaceMacro} onChange={(_e, v) => set({ replaceMacro: v })}
                        label={`Replace the custom startup macro (${st.macro})`} />
              <Help problem={problems.replaceMacro} />
            </FormGroup>
          )}
          <FormGroup label="Post node status" fieldId="node-statpost">
            <Switch id="node-statpost" isChecked={draft.statpost} isDisabled={node.private}
                    label="Posting to stats.allstarlink.org" onChange={(_e, v) => set({ statpost: v })} />
            <Help hint={node.private ? "Private nodes cannot post status." : undefined} />
          </FormGroup>
        </Form>
      </CardBody>
    </Card>
  );
}

function Interface({ node, list, draft, set }: { node: NodeDetail; list: NodeList; draft: Draft; set: SetDraft }) {
  return (
    <Card>
      <CardTitle>Radio interface</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <Content component="p">
            Now: <b>{INTERFACE_NAMES[node.interface ?? ""] ?? "unknown"}</b> (<code>rxchannel = {node.rxchannel ?? "—"}</code>)
          </Content>
          <Form onSubmit={(e) => e.preventDefault()}>
            <FormGroup role="radiogroup" fieldId="iface" label="Radio interface" isStack>
              {list.interfaces.map((i) => (
                <Radio key={i.id} id={`node-iface-${i.id}`} name="node-iface" label={i.label} isChecked={draft.iface === i.id}
                       onChange={() => set({ iface: i.id })} />
              ))}
            </FormGroup>
          </Form>
          <Content component="p" className="asl-sub">
            Changing the interface also loads the matching Asterisk channel driver. The old interface's settings are
            kept, in case you switch back.
          </Content>
        </div>
      </CardBody>
    </Card>
  );
}

// Shown on the tabs whose changes do not wait for "Review and save".
function Immediate({ children }: { children: ReactNode }) {
  return <Alert variant="info" isInline title="Changes on this tab take effect immediately">{children}</Alert>;
}

function Tuning({ node, status }: { node: NodeDetail; status: Status | null }) {
  if (node.interface === "SimpleUSB" || node.interface === "USBRadio") {
    return (
      <div className="asl-stack">
        <Immediate>
          Each setting reaches the radio interface as soon as you apply it; it is not part of Review and save.
          Save settings writes them to the configuration file so that they survive a restart of Asterisk.
        </Immediate>
        <TuningPanel node={node.number} status={status} />
      </div>
    );
  }
  return (
    <Card>
      <CardTitle>Tuning</CardTitle>
      <CardBody>
        <Content component="p">
          {node.interface === "Pseudo" ? "A node with no radio interface needs no tuning." :
            `${INTERFACE_NAMES[node.interface ?? ""] ?? "This interface"} is not tuned here; edit its settings in Manual Config Edit.`}
        </Content>
      </CardBody>
    </Card>
  );
}

function Access({ node }: { node: NodeDetail }) {
  const [lists, setLists] = useState<AccessLists | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"allow" | "deny">("allow");
  const [entry, setEntry] = useState("");
  const [reason, setReason] = useState("");

  const run = useCallback(async (fn: () => Promise<AccessLists>) => {
    setError(null);
    try {
      const l = await fn();
      setLists(l);
      if (l.mode !== "open") setKind(l.mode);
      return true;
    } catch (err) {
      setError(message(err));
      return false;
    }
  }, []);

  useEffect(() => {
    void run(() => getAccess(node.number));
  }, [node.number, run]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (await run(() => addAccess(node.number, kind, entry, reason))) {
      setEntry("");
      setReason("");
    }
  };

  const shown = lists ? (lists.mode === "deny" ? lists.deny : lists.allow) : [];
  const both = lists && lists.allow.length > 0 && lists.deny.length > 0;
  return (
    <Card>
      <CardTitle>Access control</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <Immediate>
            Allowing, blocking and removing entries changes the node's access list at once, with no restart; it is
            not part of Review and save.
          </Immediate>
          {error && <Alert variant="danger" isInline title={error} />}
          {!lists && !error && <Spinner size="md" aria-label="Loading" />}
          {lists && (
            <>
              <Content component="p">
                {lists.mode === "open" && <>Any node may connect to node {node.number}.</>}
                {lists.mode === "allow" && <>Only the nodes and calls below may connect to node {node.number}.</>}
                {lists.mode === "deny" && <>Every node may connect to node {node.number} except those below.</>}
              </Content>
              {both && (
                <Alert variant="warning" isInline isPlain
                       title="The node has both lists. The allow list is used; the deny list is ignored." />
              )}
              {shown.length > 0 && (
                <Table aria-label="Access list" variant="compact">
                  <Thead>
                    <Tr>
                      <Th>{lists.mode === "deny" ? "Blocked" : "Allowed"}</Th>
                      <Th>Reason</Th>
                      <Th screenReaderText="Actions" />
                    </Tr>
                  </Thead>
                  <Tbody>
                    {shown.map((e) => (
                      <Tr key={e.entry}>
                        <Td dataLabel="Node or call">{e.entry}</Td>
                        <Td dataLabel="Reason">{e.reason || <span className="asl-sub">—</span>}</Td>
                        <Td isActionCell>
                          <Button variant="link" isInline isDanger
                                  onClick={() => run(() => removeAccess(node.number, lists.mode, e.entry))}>
                            Remove
                          </Button>
                        </Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              )}
              <Form onSubmit={add}>
                {lists.mode === "open" && (
                  <FormGroup label="Limit access by" fieldId="access-kind">
                    <ToggleGroup aria-label="List type">
                      <ToggleGroupItem text="Allowing only listed nodes" isSelected={kind === "allow"} onChange={() => setKind("allow")} />
                      <ToggleGroupItem text="Blocking listed nodes" isSelected={kind === "deny"} onChange={() => setKind("deny")} />
                    </ToggleGroup>
                  </FormGroup>
                )}
                <div className="asl-form-row">
                  <FormGroup label="Node number or call sign" fieldId="access-entry">
                    <PlainTextInput id="access-entry" value={entry} onChange={(_e, v) => setEntry(v)} />
                  </FormGroup>
                  <FormGroup label="Reason (optional)" fieldId="access-reason">
                    <PlainTextInput id="access-reason" value={reason} onChange={(_e, v) => setReason(v)} />
                  </FormGroup>
                </div>
                <ActionGroup>
                  <Button type="submit" isDisabled={!entry.trim()}>{kind === "allow" ? "Allow" : "Block"}</Button>
                  {shown.length > 0 && (
                    <Button variant="link" isDanger onClick={() => run(() => clearAccess(node.number, lists.mode))}>
                      Remove all
                    </Button>
                  )}
                </ActionGroup>
              </Form>
            </>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function Customizations({ node, draft, set, enable }: {
  node: NodeDetail; draft: Draft; set: SetDraft; enable: () => Promise<unknown>;
}) {
  const status = node.customizations;
  const [error, setError] = useState<string | null>(null);
  const devices = status.options.filter((o) => o.device);
  const chosen = draft.custom;
  const chosenDevice = devices.find((d) => chosen.includes(d.name));
  const toggle = (name: string, on: boolean) => set({ custom: on ? [...chosen, name] : chosen.filter((n) => n !== name) });

  const prepare = async () => {
    setError(null);
    try {
      await enable();
    } catch (err) {
      setError(message(err));
    }
  };

  return (
    <Card>
      <CardTitle>Customizations</CardTitle>
      <CardBody>
        <div className="asl-stack">
          {error && <Alert variant="danger" isInline title={error} />}
          {status.state === "unavailable" ? (
            <>
              <Content component="p">{status.reason}</Content>
              {status.can_enable && (
                <>
                  <Content component="p">
                    Older configuration files can be rearranged to support customizations. You will see every change
                    before it is saved.
                  </Content>
                  <ActionGroup>
                    <Button onClick={prepare}>Prepare the files for customizations</Button>
                  </ActionGroup>
                </>
              )}
            </>
          ) : (
            <Form onSubmit={(e) => e.preventDefault()}>
              <Content component="p">
                Ready-made changes for common hardware and needs, from <code>/etc/asterisk/custom</code>.
              </Content>
              {devices.length > 0 && (
                <FormGroup label="Device" fieldId="custom-device" isStack>
                  {devices.map((d) => (
                    <Checkbox key={d.name} id={`dev-${d.name}`} label={d.description.replace(/\*/g, "")}
                              isChecked={chosen.includes(d.name)}
                              isDisabled={chosenDevice !== undefined && chosenDevice.name !== d.name}
                              onChange={(_e, v) => toggle(d.name, v)} />
                  ))}
                </FormGroup>
              )}
              <FormGroup label="Other" fieldId="custom-other" isStack>
                {status.options.filter((o) => !o.device).map((o) => (
                  <Checkbox key={o.name} id={`opt-${o.name}`} label={o.description} isChecked={chosen.includes(o.name)}
                            onChange={(_e, v) => toggle(o.name, v)} />
                ))}
              </FormGroup>
            </Form>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

const TABS = ["general", "interface", "tuning", "access", "customizations"] as const;
const TAB_NAMES: Record<(typeof TABS)[number], string> = {
  general: "General", interface: "Radio interface", tuning: "Tuning", access: "Access control",
  customizations: "Customizations",
};
const DRAFT_TABS = ["general", "interface", "customizations"];

export function NodePage({ number, tab, status }: { number: string; tab: string; status: Status | null }) {
  const [node, setNode] = useState<NodeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [list, , reloadList] = useNodeList();
  const [changeElement, propose, proposeOps] = useChange();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const n = await getNode(number);
      setNode(n);
      setDraft(initial(n));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 404 ? `Node ${number} is not configured.` : message(err));
    }
  }, [number]);

  useEffect(() => {
    setNode(null);
    void load();
  }, [load]);

  const set: SetDraft = useCallback((change) => {
    setSaveError(null);
    setDraft((d) => (d ? { ...d, ...change } : d));
  }, []);

  const pending = useMemo(() => (node && list && draft ? changes(node, list, draft) : { ops: [], problems: {} }),
    [node, list, draft]);
  const dirty = pending.ops.length > 0;
  const valid = Object.keys(pending.problems).length === 0;
  const dirtyTabs = new Set(pending.ops.map((o) => o.tab));
  const count = pending.ops.filter((o) => o.op !== "permanent_links").length;

  // Leaving the node's pages, closing or reloading the browser tab would lose the draft.
  const stays = useCallback((r: string) => r === `nodes/${number}` || r.startsWith(`nodes/${number}/`), [number]);
  useLeaveGuard(dirty ? stays : null);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = async () => {
    setSaveError(null);
    const renamed = draft && node && draft.number !== node.number ? draft.number : null;
    try {
      const res = await proposeOps(pending.ops.map(({ tab: _tab, ...op }) => op));
      if (!res) return;
      if (renamed) {
        go(`nodes/${renamed}/${active}`, true);
        return;
      }
      await Promise.all([load(), reloadList()]);
    } catch (err) {
      setSaveError(message(err));
      // Show the tab with the setting the server refused.
      const op = err instanceof ApiError ? err.data.op : undefined;
      const where = pending.ops.find((o) => o.op === op)?.tab;
      if (where && where !== active) go(`nodes/${number}/${where}`);
    }
  };

  const discard = () => {
    setSaveError(null);
    if (node) setDraft(initial(node));
  };

  // Changes made outside the draft (removing the node, preparing customizations).
  const now = async (op: string, params: Record<string, unknown>) => {
    const res = await propose(op, params);
    if (res) await Promise.all([load(), reloadList()]);
    return res;
  };

  const remove = async () => {
    try {
      if (await propose("remove", { node: number })) go("nodes", true);
    } catch (err) {
      setError(message(err));
    }
  };

  const active = (TABS as readonly string[]).includes(tab) ? (tab as (typeof TABS)[number]) : "general";
  const showBar = node && list && draft && (dirty || DRAFT_TABS.includes(active));
  return (
    <>
      <PageSection className="asl-page-head">
        <Breadcrumb>
          <BreadcrumbItem to="#/nodes">Nodes</BreadcrumbItem>
          <BreadcrumbItem isActive>{number}</BreadcrumbItem>
        </Breadcrumb>
        <div className="asl-title-row">
          <Title headingLevel="h1">
            Node {number}
            {node?.callsign && <span className="asl-title-sub"> · {node.callsign}</span>}
          </Title>
          {node && (
            <Button variant="secondary" isDanger onClick={remove}>
              Remove node
            </Button>
          )}
        </div>
        <Tabs activeKey={active} onSelect={(_e, key) => go(`nodes/${number}/${key}`)} className="asl-head-tabs">
          {TABS.map((t) => (
            <Tab key={t} eventKey={t} title={
              <TabTitleText>
                {TAB_NAMES[t]}
                {dirtyTabs.has(t) && <span className="asl-dirty" title="Unsaved changes" aria-label="(unsaved changes)" />}
              </TabTitleText>
            } />
          ))}
        </Tabs>
      </PageSection>
      <PageSection>
        {error && <Alert variant="danger" isInline title={error} />}
        {(!node || !list || !draft) && !error && <Spinner aria-label="Loading" />}
        {node && list && draft && (
          <>
            {active === "general" && (
              <General node={node} list={list} status={status} draft={draft} set={set} problems={pending.problems} />
            )}
            {active === "interface" && <Interface node={node} list={list} draft={draft} set={set} />}
            {active === "tuning" && <Tuning node={node} status={status} />}
            {active === "access" && <Access node={node} />}
            {active === "customizations" && (
              <Customizations node={node} draft={draft} set={set}
                              enable={() => now("enable_customizations", { node: node.number })} />
            )}
          </>
        )}
      </PageSection>
      {showBar && (
        <PageSection className="asl-save-bar" stickyOnBreakpoint={{ default: "bottom" }} aria-label="Unsaved changes">
          <div className="asl-save-row">
            <Button onClick={save} isDisabled={!dirty || !valid}>Review and save</Button>
            <Button variant="link" onClick={discard} isDisabled={!dirty}>Discard changes</Button>
            <span className="asl-sub">
              {!dirty ? "No unsaved changes." :
                !valid ? "Correct the highlighted settings first." :
                `${count} unsaved change${count === 1 ? "" : "s"}` +
                ` (${[...dirtyTabs].map((t) => TAB_NAMES[t as (typeof TABS)[number]]).join(", ")}).`}
            </span>
          </div>
          {saveError && <Alert variant="danger" isInline isPlain title={saveError} />}
        </PageSection>
      )}
      {changeElement}
    </>
  );
}
