import { useState } from "react";
import {
  ActionGroup,
  Alert,
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
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Switch,
} from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";

import { NodeDetail, VoterStatus } from "./nodesApi";
import { PlainTextInput } from "./PlainInput";

// An RTCM/voter node's voter.conf, as part of the node page's draft (see
// NodePage): the voting clients, the instance's settings, and the
// [general] settings every voter node on the server shares.

export type VoterClientDraft = {
  key: string;
  original: string | null;
  name: string;
  password: string; // empty: keep the current one
  transmit: boolean;
  master: boolean;
  nodeemp: boolean;
  noplfilter: boolean;
  gpsid: string;
  prio: string;
};

export type VoterDraft = {
  clients: VoterClientDraft[];
  settings: Record<string, string>;
  general: Record<string, string>;
  hostPassword: string; // empty: keep
};

const INSTANCE: { key: string; label: string; hint: string; kind?: "bool" | "toc" }[] = [
  { key: "plfilter", label: "Filter out CTCSS tones", kind: "bool",
    hint: "A 300 Hz high-pass filter on the voted audio (the RTCM boards filter PL already)." },
  { key: "hostdeemp", label: "De-emphasis on this server", kind: "bool",
    hint: "For boards set to duplex mode 3 that send audio without de-emphasis." },
  { key: "mixminus", label: "Mix-minus", kind: "bool", hint: "Mix-minus audio for clients in mix (non-voting) mode." },
  { key: "thresholds", label: "Thresholds", hint: "RSSI[=REASSESS[:LINGER]], comma separated, for example 255,110=5." },
  { key: "linger", label: "Linger (frames)", hint: "How long a voted client stays selected; default 6." },
  { key: "buflen", label: "Buffer (ms)", hint: "Overrides the server's buffer length for this node; at least 40." },
  { key: "txctcss", label: "Transmit CTCSS (Hz)", hint: "For example 100.0; empty sends no tone." },
  { key: "txctcsslevel", label: "Transmit CTCSS level", hint: "0 to 250; default 62." },
  { key: "txtoctype", label: "Tone at unkey", kind: "toc", hint: "What the CTCSS tone does when the transmitter unkeys." },
  { key: "gtxgain", label: "Transmit gain (dB)", hint: "Applied to the audio sent to every transmitter." },
];

export function voterDraft(v: VoterStatus | null): VoterDraft {
  return {
    clients: (v?.clients ?? []).map((c) => ({
      key: c.name, original: c.name, name: c.name, password: "", transmit: c.transmit, master: c.master,
      nodeemp: c.nodeemp, noplfilter: c.noplfilter, gpsid: c.gpsid ?? "", prio: c.prio === null ? "" : String(c.prio),
    })),
    settings: { ...(v?.settings ?? {}) },
    general: { ...(v?.general ?? {}) },
    hostPassword: "",
  };
}

// The "voter" plan operation, or null when nothing changed.
export function voterOp(base: VoterDraft, d: VoterDraft): Record<string, unknown> | null {
  const strip = (x: VoterDraft) => JSON.stringify({ ...x, clients: x.clients.map(({ key: _k, ...c }) => c) });
  if (strip(base) === strip(d)) return null;
  const diff = (a: Record<string, string>, b: Record<string, string>) =>
    Object.fromEntries([...new Set([...Object.keys(a), ...Object.keys(b)])]
      .filter((k) => (a[k] ?? "") !== (b[k] ?? "")).map((k) => [k, b[k] ?? ""]));
  return {
    clients: d.clients.map((c) => ({
      original: c.original, name: c.name.trim(), password: c.password || null, transmit: c.transmit,
      master: c.master, nodeemp: c.nodeemp, noplfilter: c.noplfilter, gpsid: c.gpsid.trim() === "" ? null : c.gpsid.trim(),
      prio: c.prio.trim() === "" ? null : c.prio.trim(),
    })),
    settings: diff(base.settings, d.settings),
    general: diff(base.general, d.general),
    host_password: d.hostPassword || null,
  };
}

const RESERVED = /^(transmit|master|gpsid|buflen|nodeemp|hostdeemp|noplfilter|prio)/i;

function clientProblem(c: VoterClientDraft, all: VoterClientDraft[]): string | null {
  if (!/^[A-Za-z0-9_.-]{1,49}$/.test(c.name.trim())) return "Letters, numbers, _ . and -, at most 49.";
  if (RESERVED.test(c.name.trim())) return "chan_voter would read this name as a setting.";
  if (all.some((o) => o.key !== c.key && o.name.trim().toLowerCase() === c.name.trim().toLowerCase())) {
    return "Another client has this name.";
  }
  if (!c.original && !c.password) return "A new client needs a password.";
  if (c.password && !/^[^\s,;=[\]]{1,49}$/.test(c.password)) return "Passwords cannot contain spaces, commas or semicolons.";
  if (c.prio.trim() && !/^-?\d+$/.test(c.prio.trim())) return "The priority is a whole number.";
  return null;
}

function ClientModal({ client, all, masterElsewhere, onClose, onSave }: {
  client: VoterClientDraft; all: VoterClientDraft[]; masterElsewhere: string[];
  onClose: () => void; onSave: (c: VoterClientDraft) => void;
}) {
  const [c, setC] = useState(client);
  const set = (change: Partial<VoterClientDraft>) => setC((x) => ({ ...x, ...change }));
  const problem = clientProblem(c, all);
  const otherMaster = all.find((o) => o.key !== c.key && o.master)?.name ?? masterElsewhere[0];
  return (
    <Modal isOpen onClose={onClose} variant="small" aria-labelledby="voter-client-title">
      <ModalHeader title={client.original ? `Client ${client.original}` : "Add a voting client"} labelId="voter-client-title" />
      <ModalBody>
        <Form id="voter-client-form" onSubmit={(e) => { e.preventDefault(); if (!problem) onSave(c); }}>
          <FormGroup label="Name" fieldId="vc-name" isRequired>
            <PlainTextInput id="vc-name" value={c.name} onChange={(_e, v) => set({ name: v })} />
            <FormHelperText><HelperText><HelperTextItem>The site, for example Hilltop.</HelperTextItem></HelperText></FormHelperText>
          </FormGroup>
          <FormGroup label="Password" fieldId="vc-password" isRequired={!client.original}>
            <PlainTextInput id="vc-password" type="password" value={c.password} autoComplete="new-password"
                            placeholder={client.original ? "Unchanged" : ""} onChange={(_e, v) => set({ password: v })} />
            <FormHelperText><HelperText><HelperTextItem>
              The board's own password. Every client needs a different one; chan_voter recognizes boards by it.
            </HelperTextItem></HelperText></FormHelperText>
          </FormGroup>
          <Checkbox id="vc-transmit" label="Has a transmitter" isChecked={c.transmit} onChange={(_e, v) => set({ transmit: v })}
                    description="Transmit audio is sent to this site." />
          <Checkbox id="vc-master" label="Master timing source" isChecked={c.master} onChange={(_e, v) => set({ master: v })}
                    isDisabled={!c.master && otherMaster !== undefined}
                    description={!c.master && otherMaster ? `The server already has one: ${otherMaster}.`
                      : "The board on the same network as this server; one per server."} />
          <Checkbox id="vc-nodeemp" label="No de-emphasis" isChecked={c.nodeemp} onChange={(_e, v) => set({ nodeemp: v })}
                    description="Only for clients that do not vote." />
          <Checkbox id="vc-noplfilter" label="No CTCSS filter on the board" isChecked={c.noplfilter}
                    onChange={(_e, v) => set({ noplfilter: v })} />
          <div className="asl-form-row">
            <FormGroup label="Priority" fieldId="vc-prio">
              <PlainTextInput id="vc-prio" value={c.prio} onChange={(_e, v) => set({ prio: v })} inputMode="numeric" placeholder="0" />
              <FormHelperText><HelperText><HelperTextItem>Only the highest-priority clients hearing a signal are voted; -1 locks the client out.</HelperTextItem></HelperText></FormHelperText>
            </FormGroup>
            <FormGroup label="GPS id" fieldId="vc-gpsid">
              <PlainTextInput id="vc-gpsid" value={c.gpsid} onChange={(_e, v) => set({ gpsid: v })} />
              <FormHelperText><HelperText><HelperTextItem>Optional, as named in gps.conf.</HelperTextItem></HelperText></FormHelperText>
            </FormGroup>
          </div>
          {problem && <Alert variant="danger" isInline isPlain title={problem} />}
        </Form>
      </ModalBody>
      <ModalFooter>
        <Button type="submit" form="voter-client-form" isDisabled={problem !== null}>Done</Button>
        <Button variant="link" onClick={onClose}>Cancel</Button>
      </ModalFooter>
    </Modal>
  );
}

export function VoterTab({ node, draft, set }: {
  node: NodeDetail; draft: VoterDraft; set: (v: VoterDraft) => void;
}) {
  const [editing, setEditing] = useState<VoterClientDraft | null>(null);
  const v = node.voter;
  const setSetting = (key: string, value: string) => set({ ...draft, settings: { ...draft.settings, [key]: value } });
  const setGeneral = (key: string, value: string) => set({ ...draft, general: { ...draft.general, [key]: value } });
  const on = (value: string | undefined) => /^(y|yes|t|true|1|on)$/i.test(value ?? "");
  const saveClient = (c: VoterClientDraft) => {
    const exists = draft.clients.some((x) => x.key === c.key);
    set({ ...draft, clients: exists ? draft.clients.map((x) => (x.key === c.key ? c : x)) : [...draft.clients, c] });
    setEditing(null);
  };
  const options = (c: VoterClientDraft) => [
    c.nodeemp && "no de-emphasis", c.noplfilter && "no CTCSS filter", c.prio.trim() && `priority ${c.prio.trim()}`,
    c.gpsid.trim() && `GPS ${c.gpsid.trim()}`,
  ].filter(Boolean).join(", ");
  const newClient = (): VoterClientDraft => ({
    key: `new-${Date.now()}`, original: null, name: "", password: "", transmit: false, master: false, nodeemp: false,
    noplfilter: false, gpsid: "", prio: "",
  });

  return (
    <div className="asl-stack">
      <Card>
        <CardTitle>Voting clients</CardTitle>
        <CardBody>
          <div className="asl-stack">
            <Content component="p">
              The RTCM or VOTER boards at each receiver and transmitter site of node {node.number}, from{" "}
              <code>/etc/asterisk/voter.conf</code>. Live signal levels are on{" "}
              <a href="/allmon3/voter.html" target="_blank" rel="noopener">Allmon3's voter page</a>
              {" "}(add {node.number} under Voters on the Allmon3 page's Nodes tab).
            </Content>
            {!v?.configured && (
              <Alert variant="info" isInline isPlain title={`voter.conf has no [${node.number}] section yet; adding a client creates it.`} />
            )}
            {draft.clients.length > 0 ? (
              <Table aria-label="Voting clients" variant="compact">
                <Thead>
                  <Tr>
                    <Th>Client</Th>
                    <Th>Transmitter</Th>
                    <Th>Options</Th>
                    <Th screenReaderText="Actions" />
                  </Tr>
                </Thead>
                <Tbody>
                  {draft.clients.map((c) => (
                    <Tr key={c.key}>
                      <Td dataLabel="Client">
                        {c.name} {c.master && <Label color="blue" isCompact>Master</Label>}
                        {!c.original && <Label color="orange" isCompact>New</Label>}
                      </Td>
                      <Td dataLabel="Transmitter">{c.transmit ? "Yes" : "Receive only"}</Td>
                      <Td dataLabel="Options">{options(c) || <span className="asl-sub">—</span>}</Td>
                      <Td isActionCell>
                        <div className="asl-buttons">
                          <Button variant="link" isInline onClick={() => setEditing(c)}>Edit</Button>
                          <Button variant="link" isInline isDanger
                                  onClick={() => set({ ...draft, clients: draft.clients.filter((x) => x.key !== c.key) })}>
                            Remove
                          </Button>
                        </div>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            ) : (
              <Content component="p" className="asl-sub">No clients are configured, so the node hears nothing.</Content>
            )}
            <ActionGroup>
              <Button variant="secondary" onClick={() => setEditing(newClient())}>Add a client</Button>
            </ActionGroup>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>Voting settings for node {node.number}</CardTitle>
        <CardBody>
          <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
            {INSTANCE.map((f) => (
              <FormGroup key={f.key} label={f.kind === "bool" ? undefined : f.label} fieldId={`voter-${f.key}`}>
                {f.kind === "bool" ? (
                  <Switch id={`voter-${f.key}`} label={f.label} isChecked={on(draft.settings[f.key])}
                          onChange={(_e, value) => setSetting(f.key, value ? "y" : "")} />
                ) : f.kind === "toc" ? (
                  <FormSelect id={`voter-${f.key}`} value={(draft.settings[f.key] ?? "").toLowerCase()}
                              onChange={(_e, value) => setSetting(f.key, value)}>
                    <FormSelectOption value="" label="Stops with the transmitter (default)" />
                    <FormSelectOption value="phase" label="Reverse burst (phase)" />
                    <FormSelectOption value="notone" label="Stops before the transmitter (notone)" />
                  </FormSelect>
                ) : (
                  <PlainTextInput id={`voter-${f.key}`} value={draft.settings[f.key] ?? ""}
                                  onChange={(_e, value) => setSetting(f.key, value)} />
                )}
                <FormHelperText><HelperText><HelperTextItem>{f.hint}</HelperTextItem></HelperText></FormHelperText>
              </FormGroup>
            ))}
          </Form>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>For every voter node on this server</CardTitle>
        <CardBody>
          <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
            <FormGroup label="Host password" fieldId="voter-host-password">
              <PlainTextInput id="voter-host-password" type="password" value={draft.hostPassword}
                              placeholder={v?.host_password_set ? "Unchanged" : "Not set"} autoComplete="new-password"
                              onChange={(_e, value) => set({ ...draft, hostPassword: value })} />
              <FormHelperText><HelperText><HelperTextItem>
                Set on every board as its host password (menu item 6).
              </HelperTextItem></HelperText></FormHelperText>
            </FormGroup>
            <FormGroup label="Buffer (ms)" fieldId="voter-g-buflen">
              <PlainTextInput id="voter-g-buflen" value={draft.general.buflen ?? ""} placeholder="480"
                              onChange={(_e, value) => setGeneral("buflen", value)} />
              <FormHelperText><HelperText><HelperTextItem>
                The longest expected network delay plus about 100 ms.
              </HelperTextItem></HelperText></FormHelperText>
            </FormGroup>
            <FormGroup label="UDP port" fieldId="voter-g-port">
              <PlainTextInput id="voter-g-port" value={draft.general.port ?? ""} placeholder="1667" inputMode="numeric"
                              onChange={(_e, value) => setGeneral("port", value)} />
              <FormHelperText><HelperText><HelperTextItem>Changing it restarts Asterisk.</HelperTextItem></HelperText></FormHelperText>
            </FormGroup>
            <FormGroup label="Listen address" fieldId="voter-g-bindaddr">
              <PlainTextInput id="voter-g-bindaddr" value={draft.general.bindaddr ?? ""} placeholder="All addresses"
                              onChange={(_e, value) => setGeneral("bindaddr", value)} />
            </FormGroup>
            <FormGroup fieldId="voter-g-utos">
              <Switch id="voter-g-utos" label="Mark voter traffic for priority (IP ToS)" isChecked={on(draft.general.utos)}
                      onChange={(_e, value) => setGeneral("utos", value ? "y" : "")} />
            </FormGroup>
            <Content component="p" className="asl-sub">
              Saving rereads voter.conf in the running Asterisk; only the port, listen address and ToS need a restart.
            </Content>
          </Form>
        </CardBody>
      </Card>

      {editing && (
        <ClientModal client={editing} all={draft.clients} masterElsewhere={v?.master_elsewhere ?? []}
                     onClose={() => setEditing(null)} onSave={saveClient} />
      )}
    </div>
  );
}
