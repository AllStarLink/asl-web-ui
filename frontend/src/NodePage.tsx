import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
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
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Form,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Label,
  PageSection,
  Radio,
  Spinner,
  Switch,
  Tab,
  Tabs,
  TabTitleText,
  TextInput,
  Title,
  ToggleGroup,
  ToggleGroupItem,
} from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";

import { ApiError, message, Status } from "./api";
import { useChange } from "./ChangeReview";
import { numberProblem } from "./NodeWizard";
import {
  AccessLists, addAccess, clearAccess, getAccess, getNode, INTERFACE_NAMES, NodeDetail, NodeList, removeAccess,
} from "./nodesApi";
import { useNodeList } from "./Nodes";
import { RegistrationLabel } from "./Overview";
import { go } from "./useRoute";

type Propose = (op: string, params: Record<string, unknown>) => Promise<unknown>;

// One setting: shows the value, and an editor after "Change".
function Setting({ label, value, children, disabled }: {
  label: string; value: ReactNode; disabled?: string; children?: (close: () => void) => ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <DescriptionListGroup>
      <DescriptionListTerm>{label}</DescriptionListTerm>
      <DescriptionListDescription>
        {editing && children ? (
          children(() => setEditing(false))
        ) : (
          <div className="asl-setting">
            <span>{value}</span>
            {children && !disabled && (
              <Button variant="link" isInline onClick={() => setEditing(true)}>
                Change
              </Button>
            )}
            {disabled && <span className="asl-sub">{disabled}</span>}
          </div>
        )}
      </DescriptionListDescription>
    </DescriptionListGroup>
  );
}

// A small form inside a Setting: runs the change, shows errors, closes when done.
function Edit({ close, onSave, children, saveLabel = "Review change", valid = true }: {
  close: () => void; onSave: () => Promise<unknown>; children: ReactNode; saveLabel?: string; valid?: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if ((await onSave()) !== null) close();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Form onSubmit={submit} className="asl-inline-form">
      {children}
      {error && <Alert variant="danger" isInline isPlain title={error} />}
      <ActionGroup>
        <Button type="submit" isLoading={busy} isDisabled={busy || !valid}>
          {saveLabel}
        </Button>
        <Button variant="link" onClick={close}>
          Cancel
        </Button>
      </ActionGroup>
    </Form>
  );
}

function Text({ id, label, value, onChange, type = "text" }: {
  id: string; label: string; value: string; onChange: (v: string) => void; type?: "text" | "password";
}) {
  return (
    <FormGroup label={label} fieldId={id}>
      <TextInput id={id} type={type} value={value} onChange={(_e, v) => onChange(v)} autoFocus autoComplete="off" />
    </FormGroup>
  );
}

function General({ node, list, propose, status }: {
  node: NodeDetail; list: NodeList; propose: Propose; status: Status | null;
}) {
  const [number, setNumber] = useState(node.number);
  const [password, setPassword] = useState("");
  const [callsign, setCallsign] = useState(node.callsign ?? "");
  const [replaceId, setReplaceId] = useState(false);
  const [duplex, setDuplex] = useState(String(node.duplex ?? 2));
  const [l2l, setL2l] = useState(node.linktolink);
  const running = status?.nodes.find((n) => n.node === node.number);
  const numberError = numberProblem(number, list.nodes.map((n) => n.number), node.number);

  const rename = async () => {
    const res = await propose("rename", { node: node.number, number });
    if (res) go(`nodes/${number}`);
    return res;
  };

  return (
    <Card>
      <CardTitle>General</CardTitle>
      <CardBody>
        <DescriptionList isHorizontal className="asl-settings">
          <Setting label="Node number" value={<b>{node.number}</b>}>
            {(close) => (
              <Edit close={close} onSave={rename} valid={!numberError && number !== node.number}>
                <Text id="node-number" label="New node number" value={number} onChange={setNumber} />
                <Content component="p" className="asl-sub">
                  {numberError && number !== node.number ? numberError :
                    "Renames the node everywhere: its settings, registration, radio interface and access list."}
                </Content>
              </Edit>
            )}
          </Setting>
          <Setting label="Registration" value={
            node.private ? <Label>Private node, not registered</Label>
              : running ? <RegistrationLabel node={running} />
              : node.registered ? <Label color="blue">Configured</Label> : <Label color="orange">Not configured</Label>
          } />
          {!node.private && (
            <Setting label="Node password" value={node.password_set ? "••••••••" : <Label color="orange">Not set</Label>}>
              {(close) => (
                <Edit close={close} onSave={() => propose("password", { node: node.number, password })}
                      valid={/^[0-9a-zA-Z_-]{6,}$/.test(password)}>
                  <Text id="node-password" label="Node password" type="password" value={password} onChange={setPassword} />
                  <Content component="p" className="asl-sub">From allstarlink.org: Portal, Node Settings.</Content>
                </Edit>
              )}
            </Setting>
          )}
          <Setting label="Call sign" value={node.callsign ?? (node.id_simple ? <Label color="orange">Not set</Label> :
            <span>Custom ID: <code>{node.idrecording}</code></span>)}>
            {(close) => (
              <Edit close={close} valid={/^[0-9A-Za-z/-]{3,}$/.test(callsign.trim()) && (node.id_simple || replaceId)}
                    onSave={() => propose("callsign", { node: node.number, callsign, replace_custom: replaceId })}>
                <Text id="node-callsign" label="Call sign" value={callsign} onChange={setCallsign} />
                {!node.id_simple && (
                  <Checkbox id="node-replace-id" isChecked={replaceId} onChange={(_e, v) => setReplaceId(v)}
                            label={`Replace the custom ID (${node.idrecording}) with the call sign`} />
                )}
              </Edit>
            )}
          </Setting>
          <Setting label="Duplex" value={`${node.duplex ?? "—"}: ${list.duplex.find((d) => d.value === node.duplex)?.label ?? ""}` +
            (node.duplex === 0 ? (node.linktolink === "yes" ? " (full duplex)" : " (half duplex)") : "")}>
            {(close) => (
              <Edit close={close}
                    onSave={() => propose("duplex", { node: node.number, duplex: Number(duplex), linktolink: duplex === "0" ? l2l : undefined })}>
                <FormGroup label="Duplex" fieldId="node-duplex">
                  <FormSelect id="node-duplex" value={duplex} onChange={(_e, v) => setDuplex(v)}>
                    {list.duplex.map((d) => <FormSelectOption key={d.value} value={String(d.value)} label={`${d.value}: ${d.label}`} />)}
                  </FormSelect>
                </FormGroup>
                {duplex === "0" && (
                  <FormGroup role="radiogroup" fieldId="node-l2l" label="With no telemetry, use" isInline>
                    <Radio id="l2l-no" name="l2l" label="Half duplex" isChecked={l2l !== "yes"} onChange={() => setL2l("no")} />
                    <Radio id="l2l-yes" name="l2l" label="Full duplex (for an external repeater controller)"
                           isChecked={l2l === "yes"} onChange={() => setL2l("yes")} />
                  </FormGroup>
                )}
              </Edit>
            )}
          </Setting>
          <Setting label="Post node status" value={
            <Switch id="node-statpost" isChecked={node.statpost} isDisabled={node.private}
                    label="Posting to stats.allstarlink.org"
                    onChange={async (_e, v) => { await propose("statpost", { node: node.number, enabled: v }).catch(() => null); }} />
          } disabled={node.private ? "Private nodes cannot post status." : undefined} />
        </DescriptionList>
      </CardBody>
    </Card>
  );
}

function Interface({ node, list, propose }: { node: NodeDetail; list: NodeList; propose: Propose }) {
  const [iface, setIface] = useState(node.interface ?? "SimpleUSB");
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setError(null);
    try {
      await propose("interface", { node: node.number, interface: iface });
    } catch (err) {
      setError(message(err));
    }
  };
  return (
    <Card>
      <CardTitle>Radio interface</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <Content component="p">
            Now: <b>{INTERFACE_NAMES[node.interface ?? ""] ?? "unknown"}</b> (<code>rxchannel = {node.rxchannel ?? "—"}</code>)
          </Content>
          <Form onSubmit={(e) => { e.preventDefault(); void save(); }}>
            <FormGroup role="radiogroup" fieldId="iface" label="Radio interface" isStack>
              {list.interfaces.map((i) => (
                <Radio key={i.id} id={`node-iface-${i.id}`} name="node-iface" label={i.label} isChecked={iface === i.id}
                       onChange={() => setIface(i.id)} />
              ))}
            </FormGroup>
            {error && <Alert variant="danger" isInline isPlain title={error} />}
            <ActionGroup>
              <Button type="submit" isDisabled={iface === node.interface}>Review change</Button>
            </ActionGroup>
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

function Tuning({ node }: { node: NodeDetail }) {
  const tool = node.interface === "SimpleUSB" ? "simpleusb-tune-menu" : node.interface === "USBRadio" ? "radio-tune-menu" : null;
  return (
    <Card>
      <CardTitle>Tuning</CardTitle>
      <CardBody>
        {tool ? (
          <Content>
            <p>Tuning sets the receive and transmit audio levels of the radio interface.</p>
            <p>
              Tuning in the browser is not available yet. For now, log in over SSH and run{" "}
              <code>sudo {tool} -n {node.number}</code>.
            </p>
          </Content>
        ) : (
          <Content component="p">
            {node.interface === "Pseudo" ? "A node with no radio interface needs no tuning." :
              `${INTERFACE_NAMES[node.interface ?? ""] ?? "This interface"} is not tuned here; edit its settings in Manual Config Edit.`}
          </Content>
        )}
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
          {error && <Alert variant="danger" isInline title={error} />}
          {!lists && !error && <Spinner size="md" aria-label="Loading" />}
          {lists && (
            <>
              <Content component="p">
                {lists.mode === "open" && <>Any node may connect to node {node.number}.</>}
                {lists.mode === "allow" && <>Only the nodes and calls below may connect to node {node.number}.</>}
                {lists.mode === "deny" && <>Every node may connect to node {node.number} except those below.</>}
                {" "}Changes take effect immediately; no restart is needed.
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
                    <TextInput id="access-entry" value={entry} onChange={(_e, v) => setEntry(v)} />
                  </FormGroup>
                  <FormGroup label="Reason (optional)" fieldId="access-reason">
                    <TextInput id="access-reason" value={reason} onChange={(_e, v) => setReason(v)} />
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

function Customizations({ node, propose }: { node: NodeDetail; propose: Propose }) {
  const status = node.customizations;
  const [chosen, setChosen] = useState<string[]>(status.selected);
  const [error, setError] = useState<string | null>(null);
  const devices = status.options.filter((o) => o.device);
  const chosenDevice = devices.find((d) => chosen.includes(d.name));
  const changed = [...chosen].sort().join() !== [...status.selected].sort().join();

  const save = async () => {
    setError(null);
    try {
      await propose("customize", { node: node.number, names: chosen });
    } catch (err) {
      setError(message(err));
    }
  };
  const enable = async () => {
    setError(null);
    try {
      await propose("enable_customizations", { node: node.number });
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
                    <Button onClick={enable}>Prepare the files for customizations</Button>
                  </ActionGroup>
                </>
              )}
            </>
          ) : (
            <Form onSubmit={(e) => { e.preventDefault(); void save(); }}>
              <Content component="p">
                Ready-made changes for common hardware and needs, from <code>/etc/asterisk/custom</code>.
              </Content>
              {devices.length > 0 && (
                <FormGroup label="Device" fieldId="custom-device" isStack>
                  {devices.map((d) => (
                    <Checkbox key={d.name} id={`dev-${d.name}`} label={d.description.replace(/\*/g, "")}
                              isChecked={chosen.includes(d.name)}
                              isDisabled={chosenDevice !== undefined && chosenDevice.name !== d.name}
                              onChange={(_e, v) => setChosen((c) => (v ? [...c, d.name] : c.filter((n) => n !== d.name)))} />
                  ))}
                </FormGroup>
              )}
              <FormGroup label="Other" fieldId="custom-other" isStack>
                {status.options.filter((o) => !o.device).map((o) => (
                  <Checkbox key={o.name} id={`opt-${o.name}`} label={o.description} isChecked={chosen.includes(o.name)}
                            onChange={(_e, v) => setChosen((c) => (v ? [...c, o.name] : c.filter((n) => n !== o.name)))} />
                ))}
              </FormGroup>
              <ActionGroup>
                <Button type="submit" isDisabled={!changed}>Review changes</Button>
              </ActionGroup>
            </Form>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

const TABS = ["general", "interface", "tuning", "access", "customizations"] as const;

export function NodePage({ number, tab, status }: { number: string; tab: string; status: Status | null }) {
  const [node, setNode] = useState<NodeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [list, , reloadList] = useNodeList();
  const [changeElement, rawPropose] = useChange();

  const load = useCallback(async () => {
    try {
      setNode(await getNode(number));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 404 ? `Node ${number} is not configured.` : message(err));
    }
  }, [number]);

  useEffect(() => {
    setNode(null);
    void load();
  }, [load]);

  // Every change reloads the page's data once it is applied.
  const propose: Propose = useCallback(async (op, params) => {
    const res = await rawPropose(op, params);
    if (res) {
      await Promise.all([load(), reloadList()]);
    }
    return res;
  }, [rawPropose, load, reloadList]);

  const remove = async () => {
    try {
      if (await rawPropose("remove", { node: number })) go("nodes");
    } catch (err) {
      setError(message(err));
    }
  };

  const active = (TABS as readonly string[]).includes(tab) ? tab : "general";
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
          <Tab eventKey="general" title={<TabTitleText>General</TabTitleText>} />
          <Tab eventKey="interface" title={<TabTitleText>Radio interface</TabTitleText>} />
          <Tab eventKey="tuning" title={<TabTitleText>Tuning</TabTitleText>} />
          <Tab eventKey="access" title={<TabTitleText>Access control</TabTitleText>} />
          <Tab eventKey="customizations" title={<TabTitleText>Customizations</TabTitleText>} />
        </Tabs>
      </PageSection>
      <PageSection>
        {error && <Alert variant="danger" isInline title={error} />}
        {(!node || !list) && !error && <Spinner aria-label="Loading" />}
        {node && list && (
          <>
            {active === "general" && <General node={node} list={list} propose={propose} status={status} />}
            {active === "interface" && <Interface key={node.interface} node={node} list={list} propose={propose} />}
            {active === "tuning" && <Tuning node={node} />}
            {active === "access" && <Access node={node} />}
            {active === "customizations" && (
              <Customizations key={node.customizations.selected.join()} node={node} propose={propose} />
            )}
          </>
        )}
      </PageSection>
      {changeElement}
    </>
  );
}
