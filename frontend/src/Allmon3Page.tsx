import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import {
  ActionGroup,
  Alert,
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
  ExpandableSection,
  Form,
  FormGroup,
  FormHelperText,
  FormSelect,
  FormSelectOption,
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
  Tab,
  Tabs,
  TabTitleText,
  Title,
} from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";

import { message } from "./api";
import {
  Allmon3Applied, Allmon3Node, Allmon3Nodes, Allmon3Overview, Allmon3Users, allmon3Nodes, allmon3Overview,
  allmon3Service, allmon3Users, allmon3Web, deleteAllmon3User, planAllmon3Nodes, planAllmon3Web,
  setAllmon3Password, setAllmon3UserNodes, WebKey,
} from "./allmon3Api";
import { Findings, useAllmon3Review } from "./Allmon3Review";
import { PlainTextInput } from "./PlainInput";
import { useReauth } from "./Reauth";
import { go } from "./useRoute";

type Notice = { variant: "success" | "warning" | "danger"; text: string } | null;

function noticeFor(applied: Allmon3Applied, done: string): Notice {
  return applied.warnings.length ? { variant: "warning", text: applied.warnings.join(" ") } : { variant: "success", text: done };
}

function Problem({ text }: { text?: string | null }) {
  if (!text) return null;
  return (
    <FormHelperText>
      <HelperText>
        <HelperTextItem variant="error">{text}</HelperTextItem>
      </HelperText>
    </FormHelperText>
  );
}

// ---- status ------------------------------------------------------------------------------

function Status({ overview, reload }: { overview: Allmon3Overview; reload: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const active = overview.service.active === "active";
  const run = async (action: "start" | "stop" | "restart") => {
    setBusy(action);
    setNotice(null);
    try {
      await allmon3Service(action);
      await reload();
    } catch (err) {
      setNotice({ variant: "danger", text: message(err) });
    } finally {
      setBusy(null);
    }
  };
  const broken = overview.files.filter((f) => f.errors > 0);
  return (
    <div className="asl-stack">
      <Card>
        <CardTitle>Allmon3</CardTitle>
        <CardBody>
          <div className="asl-stack">
            <Content component="p">
              Allmon3 is AllStarLink's web page for watching nodes: who is connected, who is talking, and (after
              logging in to Allmon3) sending commands to Asterisk.
            </Content>
            {notice && <Alert variant={notice.variant} isInline title={notice.text} />}
            <DescriptionList isHorizontal>
              <DescriptionListGroup>
                <DescriptionListTerm>Service</DescriptionListTerm>
                <DescriptionListDescription>
                  {active ? <Label color="green">Running</Label>
                    : <Label color="orange">{overview.service.active === "failed" ? "Failed" : "Stopped"}</Label>}
                  {overview.service.enabled === "disabled" && <span className="asl-sub"> (not started at boot)</span>}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Monitors</DescriptionListTerm>
                <DescriptionListDescription>
                  {overview.nodes.length ? `Node${overview.nodes.length > 1 ? "s" : ""} ${overview.nodes.join(", ")}`
                    : <Label color="orange">No nodes</Label>}
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>
            <div className="asl-buttons">
              <Button component="a" href={overview.url} target="_blank" rel="noopener">Open Allmon3</Button>
              {active ? (
                <>
                  <Button variant="secondary" onClick={() => run("restart")} isLoading={busy === "restart"}
                          isDisabled={busy !== null}>Restart</Button>
                  <Button variant="secondary" isDanger onClick={() => run("stop")} isLoading={busy === "stop"}
                          isDisabled={busy !== null}>Stop</Button>
                </>
              ) : (
                <Button variant="secondary" onClick={() => run("start")} isLoading={busy === "start"}
                        isDisabled={busy !== null}>Start</Button>
              )}
            </div>
          </div>
        </CardBody>
      </Card>
      {broken.length > 0 && (
        <Alert variant="danger" isInline title="Allmon3 cannot load some of its files"
               actionLinks={<Button variant="link" isInline onClick={() => go("allmon3/files")}>Show the files</Button>}>
          {broken.map((f) => f.name).join(", ")}
        </Alert>
      )}
    </div>
  );
}

// ---- nodes (allmon3.ini) -------------------------------------------------------------------

type NodeForm = {
  original: string | null;
  node: string;
  host: string;
  port: string;
  user: string;
  passMode: "keep" | "ami" | "value";
  pass: string;
  advanced: Record<string, string>;
};

const ADVANCED: { key: keyof Allmon3Node; label: string; hint: string }[] = [
  { key: "multinodes", label: "Nodes on this server", hint: "For a server with several nodes: all of them, comma separated." },
  { key: "voters", label: "Voters", hint: "Voter node numbers to show on Allmon3's voter page, comma separated." },
  { key: "pollinterval", label: "Poll interval (seconds)", hint: "How often Asterisk is asked for the status; default 1." },
  { key: "vpollinterval", label: "Voter poll interval (seconds)", hint: "Default 1." },
  { key: "retryinterval", label: "Retry interval (seconds)", hint: "Wait before reconnecting to Asterisk; default 15." },
  { key: "retrycount", label: "Retries", hint: "Give up after this many; empty retries forever." },
  { key: "iframepre", label: "Page above", hint: "A web page shown above the node's table." },
  { key: "iframepost", label: "Page below", hint: "A web page shown below the node's table." },
];

function NodeModal({ form, data, onClose, onSave }: {
  form: NodeForm; data: Allmon3Nodes; onClose: () => void; onSave: (f: NodeForm) => Promise<void>;
}) {
  const [f, setF] = useState(form);
  const [error, setError] = useState<{ field?: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (change: Partial<NodeForm>) => setF((x) => ({ ...x, ...change }));
  const local = ["127.0.0.1", "localhost", "::1"].includes(f.host.trim());
  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSave(f);
    } catch (err) {
      const field = (err as { data?: { field?: string } }).data?.field;
      setError({ field, text: message(err) });
    } finally {
      setBusy(false);
    }
  };
  const fieldError = (name: string) => (error?.field === name ? error.text : null);
  return (
    <Modal isOpen onClose={onClose} variant="medium" aria-labelledby="a3-node-title">
      <ModalHeader title={form.original ? `Node ${form.original} in Allmon3` : "Add a node to Allmon3"} labelId="a3-node-title" />
      <ModalBody>
        <Form id="a3-node-form" onSubmit={submit}>
          {error && !error.field && <Alert variant="danger" isInline title={error.text} />}
          <div className="asl-form-row">
            <FormGroup label="Node number" fieldId="a3-node" isRequired>
              <PlainTextInput id="a3-node" value={f.node} onChange={(_e, v) => set({ node: v.trim() })} inputMode="numeric" />
              <Problem text={fieldError("node")} />
            </FormGroup>
            <FormGroup label="Asterisk server" fieldId="a3-host" isRequired>
              <PlainTextInput id="a3-host" value={f.host} onChange={(_e, v) => set({ host: v })} />
              <Problem text={fieldError("host")} />
            </FormGroup>
          </div>
          <div className="asl-form-row">
            <FormGroup label="AMI port" fieldId="a3-port">
              <PlainTextInput id="a3-port" value={f.port} onChange={(_e, v) => set({ port: v.trim() })}
                              placeholder="5038" inputMode="numeric" />
            </FormGroup>
            <FormGroup label="AMI user" fieldId="a3-user" isRequired>
              <PlainTextInput id="a3-user" value={f.user} onChange={(_e, v) => set({ user: v })} />
              <Problem text={fieldError("user")} />
            </FormGroup>
          </div>
          <FormGroup role="radiogroup" fieldId="a3-pass" label="AMI secret" isStack>
            {form.original && (
              <Radio id="a3-pass-keep" name="a3-pass" label="Keep the current secret" isChecked={f.passMode === "keep"}
                     onChange={() => set({ passMode: "keep" })} />
            )}
            {local && (
              <Radio id="a3-pass-ami" name="a3-pass" isChecked={f.passMode === "ami"} onChange={() => set({ passMode: "ami" })}
                     label={`Use the secret of AMI user "${f.user}" from manager.conf`}
                     description={data.ami_users.includes(f.user.trim()) ? undefined : `manager.conf has no user "${f.user}".`} />
            )}
            <Radio id="a3-pass-value" name="a3-pass" label="Enter the secret" isChecked={f.passMode === "value"}
                   onChange={() => set({ passMode: "value" })} />
            {f.passMode === "value" && (
              <PlainTextInput id="a3-pass-input" type="password" value={f.pass} onChange={(_e, v) => set({ pass: v })}
                              aria-label="AMI secret" autoComplete="new-password" />
            )}
            <Problem text={fieldError("pass")} />
          </FormGroup>
          <ExpandableSection toggleText="More settings">
            <div className="asl-stack">
              {ADVANCED.map((a) => (
                <FormGroup key={a.key} label={a.label} fieldId={`a3-${a.key}`}>
                  <PlainTextInput id={`a3-${a.key}`} value={f.advanced[a.key] ?? ""}
                                  onChange={(_e, v) => set({ advanced: { ...f.advanced, [a.key]: v } })} />
                  <FormHelperText><HelperText><HelperTextItem>{a.hint}</HelperTextItem></HelperText></FormHelperText>
                  <Problem text={fieldError(a.key)} />
                </FormGroup>
              ))}
            </div>
          </ExpandableSection>
        </Form>
      </ModalBody>
      <ModalFooter>
        <Button type="submit" form="a3-node-form" isLoading={busy} isDisabled={busy || !f.node || !f.host.trim() || !f.user.trim()}>
          Review change
        </Button>
        <Button variant="link" onClick={onClose}>Cancel</Button>
      </ModalFooter>
    </Modal>
  );
}

function Nodes() {
  const [data, setData] = useState<Allmon3Nodes | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [editing, setEditing] = useState<NodeForm | null>(null);
  const [reviewElement, review] = useAllmon3Review();

  const load = useCallback(async () => {
    try {
      setData(await allmon3Nodes());
      setError(null);
    } catch (err) {
      setError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const change = async (body: Record<string, unknown>, done: string) => {
    setNotice(null);
    const applied = await review(planAllmon3Nodes(body));
    if (applied) {
      setNotice(noticeFor(applied, done));
      await load();
    }
    return applied;
  };

  const run = async (body: Record<string, unknown>, done: string) => {
    try {
      await change(body, done);
    } catch (err) {
      setNotice({ variant: "danger", text: message(err) });
    }
  };

  const save = async (f: NodeForm) => {
    const body: Record<string, unknown> = {
      op: "set", node: f.node, original: f.original, host: f.host, port: f.port, user: f.user,
      pass_mode: f.passMode, pass: f.pass,
    };
    for (const a of ADVANCED) body[a.key] = f.advanced[a.key] ?? "";
    if (await change(body, `Node ${f.node} saved; Allmon3 restarted.`)) setEditing(null);
  };

  const edit = (n: Allmon3Node) => setEditing({
    original: n.node, node: n.node, host: n.host ?? "", port: n.port ?? "", user: n.user ?? "", passMode: "keep",
    pass: "", advanced: Object.fromEntries(ADVANCED.map((a) => [a.key, String(n[a.key] ?? "")])),
  });
  const add = () => setEditing({
    original: null, node: data?.local.find((l) => !l.listed)?.number ?? "", host: "127.0.0.1", port: "",
    user: data?.ami_users.includes("admin") ? "admin" : data?.ami_users[0] ?? "admin", passMode: "ami", pass: "",
    advanced: {},
  });

  if (error) return <Alert variant="danger" isInline title={error} />;
  if (!data) return <Spinner aria-label="Loading" />;
  const missing = data.local.filter((l) => !l.listed).map((l) => l.number);
  return (
    <Card>
      <CardTitle>Nodes</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <Content component="p">
            The nodes Allmon3 shows, and how it reaches each one's Asterisk manager (AMI). From{" "}
            <code>/etc/allmon3/allmon3.ini</code>.
          </Content>
          {notice && <Alert variant={notice.variant} isInline title={notice.text} />}
          <Findings findings={data.findings} />
          {missing.length > 0 && (
            <Alert variant="info" isInline title={`Allmon3 does not show node${missing.length > 1 ? "s" : ""} ${missing.join(", ")} on this server`}
                   actionLinks={<Button variant="link" isInline
                                        onClick={() => run({ op: "add_local" }, "Added; Allmon3 restarted.")}>
                     Add {missing.length > 1 ? "them" : "it"}
                   </Button>}>
              Adds {missing.length > 1 ? "them" : "it"} with this server's AMI user admin and its secret.
            </Alert>
          )}
          {data.nodes.length > 0 && (
            <Table aria-label="Allmon3 nodes" variant="compact">
              <Thead>
                <Tr>
                  <Th>Node</Th>
                  <Th>Asterisk server</Th>
                  <Th>AMI user</Th>
                  <Th>AMI secret</Th>
                  <Th screenReaderText="Actions" />
                </Tr>
              </Thead>
              <Tbody>
                {data.nodes.map((n) => (
                  <Tr key={n.node}>
                    <Td dataLabel="Node">
                      {n.node}
                      {n.multinodes && <div className="asl-sub">with {n.multinodes}</div>}
                    </Td>
                    <Td dataLabel="Asterisk server">{n.host}{n.port ? `:${n.port}` : ""}</Td>
                    <Td dataLabel="AMI user">{n.user}</Td>
                    <Td dataLabel="AMI secret">
                      {!n.pass_set ? <Label color="red">Missing</Label>
                        : n.pass_matches_ami ? <Label color="green">Matches manager.conf</Label>
                        : n.local_host ? <Label color="orange">Differs from manager.conf</Label>
                        : <Label>Set</Label>}
                    </Td>
                    <Td isActionCell>
                      <div className="asl-buttons">
                        <Button variant="link" isInline onClick={() => edit(n)}>Edit</Button>
                        <Button variant="link" isInline isDanger
                                onClick={() => run({ op: "remove", node: n.node }, `Node ${n.node} removed from Allmon3.`)}>
                          Remove
                        </Button>
                      </div>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
          <ActionGroup>
            <Button variant="secondary" onClick={add}>Add a node</Button>
          </ActionGroup>
        </div>
      </CardBody>
      {editing && <NodeModal form={editing} data={data} onClose={() => setEditing(null)} onSave={save} />}
      {reviewElement}
    </Card>
  );
}

// ---- users ---------------------------------------------------------------------------------

function PasswordModal({ user, onClose, onDone }: {
  user: string | null; onClose: () => void; onDone: (notice: Notice) => void;
}) {
  const [name, setName] = useState(user ?? "");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reauthElement, withReauth] = useReauth();
  const mismatch = again !== "" && again !== password;
  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await withReauth(() => setAllmon3Password(name.trim(), password));
      if (res) onDone(noticeFor(res, res.created ? `Allmon3 user ${name} added; Allmon3 restarted.`
        : `${name}'s Allmon3 password changed; Allmon3 restarted.`));
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {reauthElement}
      <Modal isOpen onClose={onClose} variant="small" aria-labelledby="a3-user-title">
        <ModalHeader title={user ? `New Allmon3 password for ${user}` : "Add an Allmon3 user"} labelId="a3-user-title" />
        <ModalBody>
          <Form id="a3-user-form" onSubmit={submit}>
            {error && <Alert variant="danger" isInline title={error} />}
            {!user && (
              <FormGroup label="User name" fieldId="a3-user-name" isRequired>
                <PlainTextInput id="a3-user-name" value={name} onChange={(_e, v) => setName(v)} autoComplete="off" />
              </FormGroup>
            )}
            <FormGroup label="Password" fieldId="a3-user-pass" isRequired>
              <PlainTextInput id="a3-user-pass" type="password" value={password} onChange={(_e, v) => setPassword(v)}
                              autoComplete="new-password" />
              <FormHelperText><HelperText><HelperTextItem>At least 8 characters.</HelperTextItem></HelperText></FormHelperText>
            </FormGroup>
            <FormGroup label="Password again" fieldId="a3-user-again" isRequired>
              <PlainTextInput id="a3-user-again" type="password" value={again} onChange={(_e, v) => setAgain(v)}
                              autoComplete="new-password" validated={mismatch ? "error" : "default"} />
              <Problem text={mismatch ? "The passwords differ." : null} />
            </FormGroup>
          </Form>
        </ModalBody>
        <ModalFooter>
          <Button type="submit" form="a3-user-form" isLoading={busy}
                  isDisabled={busy || !name.trim() || password.length < 8 || again !== password}>
            {user ? "Change password" : "Add user"}
          </Button>
          <Button variant="link" onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </>
  );
}

function LimitModal({ user, current, nodes, onClose, onDone }: {
  user: string; current: string[] | null; nodes: string[]; onClose: () => void; onDone: (notice: Notice) => void;
}) {
  const [limited, setLimited] = useState(current !== null);
  const [chosen, setChosen] = useState<string[]>(current ?? []);
  const [other, setOther] = useState((current ?? []).filter((n) => !nodes.includes(n)).join(", "));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reauthElement, withReauth] = useReauth();
  const extra = other.split(/[\s,]+/).filter(Boolean);
  const list = [...new Set([...chosen.filter((n) => nodes.includes(n)), ...extra])];
  const valid = !limited || (list.length > 0 && extra.every((n) => /^[0-9]+$/.test(n)));
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await withReauth(() => setAllmon3UserNodes(user, limited ? list : null));
      if (res) onDone(noticeFor(res, `${user} may now command ${limited ? `node${list.length > 1 ? "s" : ""} ${list.join(", ")}` : "every node"}.`));
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {reauthElement}
      <Modal isOpen onClose={onClose} variant="small" aria-labelledby="a3-limit-title">
        <ModalHeader title={`Nodes ${user} may command`} labelId="a3-limit-title" />
        <ModalBody>
          <Form onSubmit={(e) => { e.preventDefault(); void submit(); }}>
            {error && <Alert variant="danger" isInline title={error} />}
            <FormGroup role="radiogroup" fieldId="a3-limit" isStack>
              <Radio id="a3-limit-all" name="a3-limit" label="Every node" isChecked={!limited} onChange={() => setLimited(false)} />
              <Radio id="a3-limit-some" name="a3-limit" label="Only these nodes" isChecked={limited} onChange={() => setLimited(true)} />
            </FormGroup>
            {limited && (
              <>
                {nodes.map((n) => (
                  <Checkbox key={n} id={`a3-limit-${n}`} label={`Node ${n}`} isChecked={chosen.includes(n)}
                            onChange={(_e, v) => setChosen((c) => (v ? [...c, n] : c.filter((x) => x !== n)))} />
                ))}
                <FormGroup label="Other nodes" fieldId="a3-limit-other">
                  <PlainTextInput id="a3-limit-other" value={other} onChange={(_e, v) => setOther(v)} inputMode="numeric" />
                  <FormHelperText><HelperText><HelperTextItem>Node numbers, comma separated.</HelperTextItem></HelperText></FormHelperText>
                </FormGroup>
              </>
            )}
          </Form>
        </ModalBody>
        <ModalFooter>
          <Button onClick={submit} isLoading={busy} isDisabled={busy || !valid}>Save</Button>
          <Button variant="link" onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </>
  );
}

function Users() {
  const [data, setData] = useState<Allmon3Users | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [password, setPassword] = useState<{ user: string | null } | null>(null);
  const [limit, setLimit] = useState<{ user: string; nodes: string[] | null } | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [reauthElement, withReauth] = useReauth();

  const load = useCallback(async () => {
    try {
      setData(await allmon3Users());
      setError(null);
    } catch (err) {
      setError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const done = async (n: Notice) => {
    setPassword(null);
    setLimit(null);
    setNotice(n);
    await load();
  };

  const remove = async () => {
    if (!removing) return;
    const user = removing;
    setRemoving(null);
    try {
      const res = await withReauth(() => deleteAllmon3User(user));
      if (res) await done(noticeFor(res, `Allmon3 user ${user} removed; Allmon3 restarted.`));
    } catch (err) {
      setNotice({ variant: "danger", text: message(err) });
    }
  };

  if (error) return <Alert variant="danger" isInline title={error} />;
  if (!data) return <Spinner aria-label="Loading" />;
  return (
    <Card>
      <CardTitle>Users</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <Content component="p">
            Anyone can watch Allmon3; logging in to it lets a user send commands to Asterisk. Allmon3 keeps its own
            users and passwords (it cannot use this server's Linux accounts, so there is nothing to synchronize).
          </Content>
          {notice && <Alert variant={notice.variant} isInline title={notice.text} />}
          {data.users.length === 0 ? (
            <Content component="p" className="asl-sub">There are no Allmon3 users, so nobody can send commands.</Content>
          ) : (
            <Table aria-label="Allmon3 users" variant="compact">
              <Thead>
                <Tr>
                  <Th>User</Th>
                  <Th>May command</Th>
                  <Th screenReaderText="Actions" />
                </Tr>
              </Thead>
              <Tbody>
                {data.users.map((u) => (
                  <Tr key={u.name}>
                    <Td dataLabel="User">{u.name}</Td>
                    <Td dataLabel="May command">{u.nodes ? `Node${u.nodes.length > 1 ? "s" : ""} ${u.nodes.join(", ")}` : "Every node"}</Td>
                    <Td isActionCell>
                      <div className="asl-buttons">
                        <Button variant="link" isInline onClick={() => setPassword({ user: u.name })}>Password</Button>
                        <Button variant="link" isInline onClick={() => setLimit({ user: u.name, nodes: u.nodes })}>Nodes</Button>
                        <Button variant="link" isInline isDanger onClick={() => setRemoving(u.name)}>Remove</Button>
                      </div>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
          {data.orphan_restrictions.length > 0 && (
            <Content component="p" className="asl-sub">
              user-restrictions also lists {data.orphan_restrictions.join(", ")}, who {data.orphan_restrictions.length > 1 ? "are" : "is"} not
              an Allmon3 user.
            </Content>
          )}
          <ActionGroup>
            <Button variant="secondary" onClick={() => setPassword({ user: null })}>Add a user</Button>
          </ActionGroup>
        </div>
      </CardBody>
      {password && <PasswordModal user={password.user} onClose={() => setPassword(null)} onDone={done} />}
      {limit && (
        <LimitModal user={limit.user} current={limit.nodes} nodes={data.nodes} onClose={() => setLimit(null)} onDone={done} />
      )}
      <Modal isOpen={removing !== null} onClose={() => setRemoving(null)} variant="small" aria-labelledby="a3-remove-title">
        <ModalHeader title={`Remove Allmon3 user ${removing ?? ""}?`} labelId="a3-remove-title" titleIconVariant="warning" />
        <ModalBody>They can no longer log in to Allmon3 or send commands.</ModalBody>
        <ModalFooter>
          <Button variant="danger" onClick={remove}>Remove</Button>
          <Button variant="link" onClick={() => setRemoving(null)}>Cancel</Button>
        </ModalFooter>
      </Modal>
      {reauthElement}
    </Card>
  );
}

// ---- web settings ----------------------------------------------------------------------------

const WEB_FIELDS: { key: WebKey; label: string; hint: ReactNode; placeholder?: string; advanced?: boolean }[] = [
  { key: "CONFIG_HEADER_TITLE", label: "Title", hint: "Shown in the middle of Allmon3's header bar.",
    placeholder: "Allmon3 Monitoring Dashboard" },
  { key: "CONFIG_HEADER_LOGO", label: "Logo",
    hint: <>An image file in <code>/usr/share/allmon3/img/</code>, at most 50 pixels high. Empty shows the AllStarLink logo.</> },
  { key: "HOME_BUTTON_URL", label: "Home button", hint: "Where Allmon3's Home button goes, for example index.html or index.html#1999.",
    placeholder: "/allmon3/" },
  { key: "HTTP_PORT", label: "HTTP port", hint: "Allmon3's own web server, behind Apache or nginx. Default 16080.", placeholder: "16080", advanced: true },
  { key: "WS_PORT_START", label: "First WebSocket port", hint: "Allmon3 uses consecutive ports from here. Default 16700.", placeholder: "16700", advanced: true },
  { key: "WS_BIND_ADDR", label: "Listen address", hint: "One IP address; empty listens on all of them.", advanced: true },
];

function WebSettings() {
  const [values, setValues] = useState<Partial<Record<WebKey, string>> | null>(null);
  const [original, setOriginal] = useState<Partial<Record<WebKey, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [reviewElement, review] = useAllmon3Review();

  const load = useCallback(async () => {
    try {
      const res = await allmon3Web();
      setValues(res.values);
      setOriginal(res.values);
      setError(null);
    } catch (err) {
      setError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const keys = [...WEB_FIELDS.map((f) => f.key), "CONFIG_MENU_SINGLE_TARGET" as WebKey];
  const changed = values ? keys.filter((k) => (values[k] ?? "") !== (original[k] ?? "")) : [];

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!values) return;
    setNotice(null);
    try {
      const applied = await review(planAllmon3Web(Object.fromEntries(changed.map((k) => [k, values[k] || null]))));
      if (applied) {
        setNotice(noticeFor(applied, "Web settings saved; Allmon3 restarted."));
        await load();
      }
    } catch (err) {
      setNotice({ variant: "danger", text: message(err) });
    }
  };

  if (error) return <Alert variant="danger" isInline title={error} />;
  if (!values) return <Spinner aria-label="Loading" />;
  const field = (f: (typeof WEB_FIELDS)[number]) => (
    <FormGroup key={f.key} label={f.label} fieldId={`a3-web-${f.key}`}>
      <PlainTextInput id={`a3-web-${f.key}`} value={values[f.key] ?? ""} placeholder={f.placeholder}
                      onChange={(_e, v) => setValues({ ...values, [f.key]: v })} />
      <FormHelperText><HelperText><HelperTextItem>{f.hint}</HelperTextItem></HelperText></FormHelperText>
    </FormGroup>
  );
  return (
    <Card>
      <CardTitle>Web settings</CardTitle>
      <CardBody>
        <Form onSubmit={save} className="asl-node-form">
          {notice && <Alert variant={notice.variant} isInline title={notice.text} />}
          {WEB_FIELDS.filter((f) => !f.advanced).map(field)}
          <FormGroup label="Menu links to other sites" fieldId="a3-web-target">
            <FormSelect id="a3-web-target" value={values.CONFIG_MENU_SINGLE_TARGET === "_blank" ? "_blank" : ""}
                        onChange={(_e, v) => setValues({ ...values, CONFIG_MENU_SINGLE_TARGET: v })}>
              <FormSelectOption value="" label="Open in the same tab" />
              <FormSelectOption value="_blank" label="Open in a new tab" />
            </FormSelect>
          </FormGroup>
          <ExpandableSection toggleText="Ports and addresses">
            <div className="asl-stack">{WEB_FIELDS.filter((f) => f.advanced).map(field)}</div>
          </ExpandableSection>
          <Content component="p" className="asl-sub">
            Allmon3's command list, node labels and voter titles are lists of free-form lines; edit them in{" "}
            <Button variant="link" isInline onClick={() => go("allmon3/files/web.ini")}>web.ini</Button>.
          </Content>
          <ActionGroup>
            <Button type="submit" isDisabled={changed.length === 0}>Review changes</Button>
            <Button variant="link" isDisabled={changed.length === 0} onClick={() => setValues(original)}>Discard</Button>
          </ActionGroup>
        </Form>
      </CardBody>
      {reviewElement}
    </Card>
  );
}

// ---- files -----------------------------------------------------------------------------------

function Files({ overview }: { overview: Allmon3Overview }) {
  return (
    <Card>
      <CardTitle>Files</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <Content component="p">
            Allmon3's settings as text, for what the other tabs do not cover, such as the sidebar menu and the
            command list. Each file is checked the way Allmon3 reads it before it is saved.
          </Content>
          <Table aria-label="Allmon3 files" variant="compact">
            <Thead>
              <Tr>
                <Th>File</Th>
                <Th>Contents</Th>
                <Th>State</Th>
              </Tr>
            </Thead>
            <Tbody>
              {overview.files.map((f) => (
                <Tr key={f.name}>
                  <Td dataLabel="File">
                    <Button variant="link" isInline onClick={() => go(`allmon3/files/${f.name}`)}>{f.name}</Button>
                  </Td>
                  <Td dataLabel="Contents">{f.description}</Td>
                  <Td dataLabel="State">
                    {!f.exists ? <Label>{f.optional ? "Not used" : "Missing"}</Label>
                      : f.errors ? <Label color="red">{f.errors} error{f.errors > 1 ? "s" : ""}</Label>
                      : f.warnings ? <Label color="orange">{f.warnings} warning{f.warnings > 1 ? "s" : ""}</Label>
                      : <Label color="green">OK</Label>}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
          <Content component="p" className="asl-sub">
            Passwords (<code>/etc/allmon3/users</code>) are changed on the Users tab only.
          </Content>
        </div>
      </CardBody>
    </Card>
  );
}

// ---- the page ----------------------------------------------------------------------------------

const TABS = { status: "Status", nodes: "Nodes", users: "Users", web: "Web settings", files: "Files" } as const;

export function Allmon3Page({ tab }: { tab: string }) {
  const [overview, setOverview] = useState<Allmon3Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setOverview(await allmon3Overview());
      setError(null);
    } catch (err) {
      setError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load, tab]);

  const active = (tab in TABS ? tab : "status") as keyof typeof TABS;
  return (
    <>
      <PageSection className="asl-page-head">
        <Title headingLevel="h1">Allmon3</Title>
        <Content component="p" className="asl-sub">The node monitoring web page on this server.</Content>
        {overview?.installed && (
          <Tabs activeKey={active} onSelect={(_e, key) => go(`allmon3/${key}`)} className="asl-head-tabs">
            {Object.entries(TABS).map(([key, title]) => (
              <Tab key={key} eventKey={key} title={<TabTitleText>{title}</TabTitleText>} />
            ))}
          </Tabs>
        )}
      </PageSection>
      <PageSection>
        {error && <Alert variant="danger" isInline title={error} />}
        {!overview && !error && <Spinner aria-label="Loading" />}
        {overview && !overview.installed && (
          <Alert variant="info" isInline title="Allmon3 is not installed">
            Install it with <code>sudo apt install allmon3</code>, then come back here to set it up.
          </Alert>
        )}
        {overview?.installed && (
          <>
            {active === "status" && <Status overview={overview} reload={load} />}
            {active === "nodes" && <Nodes />}
            {active === "users" && <Users />}
            {active === "web" && <WebSettings />}
            {active === "files" && <Files overview={overview} />}
          </>
        )}
      </PageSection>
    </>
  );
}
