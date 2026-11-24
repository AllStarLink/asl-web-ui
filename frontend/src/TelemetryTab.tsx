import { ReactNode, useState } from "react";
import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Content,
  Form,
  FormGroup,
  FormHelperText,
  FormSelect,
  FormSelectOption,
  HelperText,
  HelperTextItem,
  Label,
  Switch,
} from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";

import { NodeDetail, Setting, TelemetryStanza, TelemetryStatus } from "./nodesApi";
import { PlainTextInput } from "./PlainInput";

// A node's ID, courtesy tones, tone definitions and Morse code, as part of
// the node page's draft (see NodePage). Each setting's draft is the line the
// node (or its stanza) has of its own, or null for none: then the template's
// value, or app_rpt's default, applies.

type Value = string | null;
export type LinkDraft = { key: string; original: string | null; node: string; tone: string };
export type TelemetryDraft = {
  settings: Record<string, Value>; // idtime and politeid in seconds; nounkeyct and nolocallinkct "1" or "0"
  links: LinkDraft[]; // linkunkeyct_<node> lines of the node's own
  tones: Record<string, Value>;
  added: string[]; // new tone names, in the order added
  morse: Record<string, Value>;
};
// Keyed "settings.idtime", "tones.ct2", "links.<key>", "morse.speed".
export type TelemetryProblems = Record<string, string>;

const SECONDS: Record<string, [number, number, string]> = {
  idtime: [60, 2400, "ID interval"], politeid: [30, 300, "Polite ID"],
};
const BOOLS = new Set(["nounkeyct", "nolocallinkct"]);
const MORSE: { key: string; label: string; unit: string; range: [number, number]; hint: string }[] = [
  { key: "speed", label: "Speed", unit: "WPM", range: [5, 35], hint: "Words per minute." },
  { key: "frequency", label: "Tone", unit: "Hz", range: [300, 3000], hint: "For |m Morse messages." },
  { key: "amplitude", label: "Level", unit: "", range: [200, 8192], hint: "For |m Morse messages." },
  { key: "idfrequency", label: "ID tone", unit: "Hz", range: [300, 3000], hint: "For the |i Morse ID." },
  { key: "idamplitude", label: "ID level", unit: "", range: [200, 8192], hint: "For the |i Morse ID." },
];
const TRUE = /^(yes|true|y|t|1|on)$/i;
const NAME = /^[A-Za-z0-9_-]+$/;
const BUILDER = "https://www.allstarlink.org/telemetry-builder/";

const msToS = (v: string) => String(Number(v) / 1000);
const sToMs = (v: string) => (/^\d+(\.\d{1,3})?$/.test(v.trim()) ? String(Math.round(Number(v) * 1000)) : null);
const boolStr = (v: string | null) => (v !== null && TRUE.test(v) ? "1" : "0");
const ownValue = (s: Setting, show: (v: string) => string = (v) => v) => (s.own && s.value !== null ? show(s.value) : null);

// How a setting is shown in the form (seconds, "1"/"0").
function shown(key: string, v: string | null): string | null {
  if (v === null) return null;
  if (key in SECONDS) return msToS(v);
  if (BOOLS.has(key)) return boolStr(v);
  return v;
}

export function telemetryDraft(t: TelemetryStatus): TelemetryDraft {
  return {
    settings: Object.fromEntries(Object.entries(t.node).map(([k, s]) => [k, ownValue(s, (v) => shown(k, v) ?? v)])),
    links: Object.entries(t.per_link).filter(([, s]) => s.own)
      .map(([n, s]) => ({ key: n, original: n, node: n, tone: s.value ?? "" })),
    tones: Object.fromEntries(t.telemetry.tones.map((x) => [x.name, ownValue(x)])),
    added: [],
    morse: Object.fromEntries(Object.entries(t.morse.settings).map(([k, s]) => [k, ownValue(s)])),
  };
}

// A telemetry value app_rpt can play (see the backend's telemetry.check_value).
export function valueProblem(v: string): string | undefined {
  const s = v.trim();
  if (!s) return undefined;
  if (s[0] === "|") {
    const mode = s[1]?.toUpperCase();
    const rest = s.slice(2);
    if (mode === "T") {
      return /^(\(\d+,\d+,\d+,\d+\))+$/.test(rest.replace(/\s+/g, ""))
        ? undefined : "Tones are |t then (tone 1,tone 2,ms,amplitude) groups.";
    }
    if (mode === "M" || mode === "I") {
      return /^[A-Za-z0-9 /.,?=+-]+$/.test(rest.trim()) ? undefined : "Morse: letters, digits, spaces and / . , ? = + -.";
    }
    return "Start with |t (tones), |m (Morse) or |i (Morse ID), or give a sound file.";
  }
  return /^[A-Za-z0-9_./-]+$/.test(s) ? undefined : "A sound file name has no spaces or extension.";
}

// The names the node's courtesy tones can choose from.
function toneNames(t: TelemetryStatus, d: TelemetryDraft): string[] {
  const defined = t.telemetry.tones.filter((x) => (d.tones[x.name] ?? x.fallback) !== null).map((x) => x.name);
  return [...defined, ...d.added.filter((n) => d.tones[n] !== null)];
}

// The "telemetry" plan operation's parameters (or null: nothing changed), and
// what is wrong with the settings that changed.
export function telemetryChanges(t: TelemetryStatus, base: TelemetryDraft, d: TelemetryDraft):
  { params: Record<string, unknown> | null; problems: TelemetryProblems } {
  const problems: TelemetryProblems = {};
  const names = new Set(toneNames(t, d).map((n) => n.toLowerCase()));
  // A value typed in that is what applies anyway needs no line of its own.
  const same = (s: Setting, file: string, key = "") =>
    !s.own && s.fallback !== null && (BOOLS.has(key) ? boolStr(s.fallback) === file : s.fallback === file);

  const settings: Record<string, unknown> = {};
  for (const [k, s] of Object.entries(t.node)) {
    const v = d.settings[k];
    if (v === base.settings[k]) continue;
    if (v === null) {
      settings[k] = null;
      continue;
    }
    let file: string | null = v;
    if (k in SECONDS) {
      const [low, high, what] = SECONDS[k];
      file = sToMs(v);
      const n = Number(v);
      if (file === null || !((n >= low && n <= high) || (k === "idtime" && n === 0))) {
        problems[`settings.${k}`] = `${what}: ${low} to ${high} seconds${k === "idtime" ? " (0: no timed ID)" : ""}.`;
      }
    } else if (k === "idrecording" || k === "idtalkover") {
      const p = valueProblem(v);
      if (p) problems[`settings.${k}`] = p;
    } else if (!BOOLS.has(k) && v && !names.has(v.toLowerCase())) {
      problems[`settings.${k}`] = `The node has no tone named ${v}.`;
    }
    if (file !== null && same(s, file, k)) {
      if (base.settings[k] !== null) settings[k] = null;
      continue;
    }
    settings[k] = BOOLS.has(k) ? v === "1" : file ?? v;
  }

  const per_link: Record<string, string | null> = {};
  const seen = new Set<string>();
  for (const b of base.links) {
    if (!d.links.some((l) => l.original === b.original && l.node.trim() === b.node)) per_link[b.node] = null;
  }
  for (const l of d.links) {
    const n = l.node.trim();
    if (!NAME.test(n)) problems[`links.${l.key}`] = "Enter the node number.";
    else if (seen.has(n)) problems[`links.${l.key}`] = `Node ${n} is listed twice.`;
    else if (l.tone && !names.has(l.tone.toLowerCase())) problems[`links.${l.key}`] = `The node has no tone named ${l.tone}.`;
    seen.add(n);
    const b = base.links.find((x) => x.original === l.original);
    if (!b || b.node !== n || b.tone !== l.tone) per_link[n] = l.tone;
  }

  const tones: Record<string, string | null> = {};
  for (const x of t.telemetry.tones) {
    const v = d.tones[x.name];
    if (v === base.tones[x.name]) continue;
    if (v !== null) {
      const p = valueProblem(v);
      if (p) problems[`tones.${x.name}`] = p;
      if (same(x, v.trim())) {
        if (base.tones[x.name] !== null) tones[x.name] = null;
        continue;
      }
    }
    tones[x.name] = v;
  }
  for (const n of d.added) {
    const v = d.tones[n];
    if (v === null) continue;
    const p = valueProblem(v);
    if (p) problems[`tones.${n}`] = p;
    tones[n] = v;
  }

  const morse: Record<string, string | null> = {};
  for (const { key, label, range: [low, high] } of MORSE) {
    const v = d.morse[key];
    if (v === base.morse[key]) continue;
    if (v !== null) {
      if (!/^\d+$/.test(v.trim()) || Number(v) < low || Number(v) > high) {
        problems[`morse.${key}`] = `${label}: ${low} to ${high}.`;
      }
      if (same(t.morse.settings[key as keyof TelemetryStatus["morse"]["settings"]], v.trim())) {
        if (base.morse[key] !== null) morse[key] = null;
        continue;
      }
    }
    morse[key] = v === null ? null : v.trim();
  }

  const any = [settings, per_link, tones, morse].some((o) => Object.keys(o).length > 0);
  return { params: any ? { settings, per_link, tones, morse } : null, problems };
}

function Help({ problem, children }: { problem?: string; children?: ReactNode }) {
  if (!problem && !children) return null;
  return (
    <FormHelperText>
      <HelperText>
        <HelperTextItem variant={problem ? "error" : "default"}>{problem ?? children}</HelperTextItem>
      </HelperText>
    </FormHelperText>
  );
}

// Where a setting's value comes from, with a way back to the inherited one.
function Source({ s, v, where, reset, show = (x) => x }: {
  s: Setting; v: Value; where: string; reset: () => void; show?: (v: string) => string;
}) {
  if (v === null) return <>{s.from ? `From [${s.from}].` : s.fallback !== null ? "app_rpt's default." : "Not set."}</>;
  return (
    <>
      Set {where}.{" "}
      <Button variant="link" isInline size="sm" onClick={reset}>
        {s.fallback === null ? "Remove" : `Use ${s.from ? `[${s.from}]'s value` : "the default"} (${show(s.fallback)})`}
      </Button>
    </>
  );
}

// Where a value set in the node's stanza is (or will be, once saved).
const stanzaFor = (stanza: TelemetryStanza, s: Setting, v: Value) =>
  stanza.in_place || (s.own && v === s.value) ? stanza.section : stanza.copy;

function StanzaNote({ stanza, number, what }: { stanza: TelemetryStanza; number: string; what: string }) {
  const others = stanza.users.filter((n) => n !== number);
  return (
    <Content component="p" className="asl-sub">
      {stanza.in_place ? <>Node {number}'s {what} are in [{stanza.section}], which only this node uses.</>
        : stanza.exists ? (
          <>
            Node {number} uses [{stanza.section}]{others.length > 0 && <>, as do node{others.length > 1 && "s"} {others.join(", ")}</>}.
            Saving a change here gives node {number} its own copy, [{stanza.copy}]
            {others.length > 0 && ", and leaves the other nodes as they are"}.
          </>
        ) : <>[{stanza.section}] does not exist, so app_rpt's built-in {what} apply. Saving a change creates [{stanza.copy}].</>}
    </Content>
  );
}

export function TelemetryTab({ node, draft, set, problems }: {
  node: NodeDetail; draft: TelemetryDraft; set: (d: TelemetryDraft) => void; problems: TelemetryProblems;
}) {
  const t = node.telemetry;
  const [newName, setNewName] = useState("");
  const setting = (k: string, v: Value) => set({ ...draft, settings: { ...draft.settings, [k]: v } });
  const tone = (n: string, v: Value) => set({ ...draft, tones: { ...draft.tones, [n]: v } });
  const morse = (k: string, v: Value) => set({ ...draft, morse: { ...draft.morse, [k]: v } });
  const links = (l: LinkDraft[]) => set({ ...draft, links: l });
  const current = (k: keyof TelemetryStatus["node"]) => draft.settings[k] ?? shown(k, t.node[k].fallback);
  const names = toneNames(t, draft);
  const known = new Set([...t.telemetry.tones.map((x) => x.name.toLowerCase()), ...draft.added.map((n) => n.toLowerCase())]);
  const nameProblem = !newName.trim() ? undefined : !NAME.test(newName.trim()) ? "Letters, numbers, _ and -."
    : known.has(newName.trim().toLowerCase()) ? "There is a tone with this name." : undefined;

  const text = (k: "idrecording" | "idtalkover", label: string, hint: ReactNode) => (
    <FormGroup label={label} fieldId={`tm-${k}`}>
      <PlainTextInput id={`tm-${k}`} value={current(k) ?? ""} onChange={(_e, v) => setting(k, v)}
                      validated={problems[`settings.${k}`] ? "error" : "default"} />
      <Help problem={problems[`settings.${k}`]}>
        {hint} <Source s={t.node[k]} v={draft.settings[k]} where="for this node" reset={() => setting(k, null)} />
      </Help>
    </FormGroup>
  );
  const seconds = (k: "idtime" | "politeid", label: string, hint: string) => (
    <FormGroup label={label} fieldId={`tm-${k}`}>
      <PlainTextInput id={`tm-${k}`} value={current(k) ?? ""} inputMode="decimal" onChange={(_e, v) => setting(k, v)}
                      validated={problems[`settings.${k}`] ? "error" : "default"} />
      <Help problem={problems[`settings.${k}`]}>
        {hint} <Source s={t.node[k]} v={draft.settings[k]} where="for this node" show={msToS}
                       reset={() => setting(k, null)} />
      </Help>
    </FormGroup>
  );
  const toneSelect = (id: string, value: string, onChange: (v: string) => void, invalid = false) => (
    <FormSelect id={id} value={value} onChange={(_e, v) => onChange(v)} validated={invalid ? "error" : "default"}>
      <FormSelectOption value="" label="No tone" />
      {value && !names.some((n) => n.toLowerCase() === value.toLowerCase()) && (
        <FormSelectOption value={value} label={`${value} (not defined)`} />
      )}
      {names.map((n) => <FormSelectOption key={n} value={n} label={n} />)}
    </FormSelect>
  );
  const ct = (k: "unlinkedct" | "remotect" | "linkunkeyct", label: string, hint: string) => (
    <FormGroup label={label} fieldId={`tm-${k}`}>
      {toneSelect(`tm-${k}`, current(k) ?? "", (v) => setting(k, v), !!problems[`settings.${k}`])}
      <Help problem={problems[`settings.${k}`]}>
        {hint} <Source s={t.node[k]} v={draft.settings[k]} where="for this node" show={(v) => v || "no tone"}
                       reset={() => setting(k, null)} />
      </Help>
    </FormGroup>
  );
  const flag = (k: "nounkeyct" | "nolocallinkct", label: string) => (
    <FormGroup fieldId={`tm-${k}`}>
      <Switch id={`tm-${k}`} label={label} isChecked={current(k) === "1"} onChange={(_e, v) => setting(k, v ? "1" : "0")} />
      <Help>
        <Source s={t.node[k]} v={draft.settings[k]} where="for this node" show={(v) => (TRUE.test(v) ? "on" : "off")}
                reset={() => setting(k, null)} />
      </Help>
    </FormGroup>
  );
  const inherited = Object.entries(t.per_link).filter(([, s]) => !s.own);

  return (
    <div className="asl-stack">
      <Card>
        <CardTitle>Identification</CardTitle>
        <CardBody>
          <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
            {text("idrecording", "ID", <>
              <code>|i</code> then the call sign sends it in Morse code at the ID tone, <code>|m</code> at the telemetry
              tone; or a sound file, such as <code>custom/myid</code>, without its extension. Empty sends no ID.
              The call sign on the General tab sets <code>|i</code> and the call sign.
            </>)}
            {text("idtalkover", "Talkover ID", "Sent instead when the ID is due while someone is talking. Empty: wait for a pause.")}
            {seconds("idtime", "ID interval (seconds)", "How often the node identifies while in use. 0: no timed ID.")}
            {seconds("politeid", "Polite ID (seconds)",
              "How long before the interval ends the node tries to identify at the end of a transmission.")}
          </Form>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>Courtesy tones</CardTitle>
        <CardBody>
          <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
            {ct("unlinkedct", "When not linked", "After a local transmission while the node has no links.")}
            {ct("remotect", "When linked", "After a local transmission while the node is linked.")}
            {ct("linkunkeyct", "After a linked node", "When a transmission from a linked node ends.")}
            <FormGroup label="For particular linked nodes" fieldId="tm-links" isStack>
              {(draft.links.length > 0 || inherited.length > 0) && (
                <Table aria-label="Courtesy tones for particular linked nodes" variant="compact">
                  <Thead>
                    <Tr><Th>Node</Th><Th>Tone</Th><Th screenReaderText="Actions" /></Tr>
                  </Thead>
                  <Tbody>
                    {inherited.map(([n, s]) => (
                      <Tr key={`from-${n}`}>
                        <Td dataLabel="Node">{n}</Td>
                        <Td dataLabel="Tone">{s.value || "No tone"}</Td>
                        <Td><span className="asl-sub">From [{s.from}]</span></Td>
                      </Tr>
                    ))}
                    {draft.links.map((l, i) => {
                      const change = (c: Partial<LinkDraft>) => links(draft.links.map((x, j) => (j === i ? { ...x, ...c } : x)));
                      return (
                        <Tr key={l.key}>
                          <Td dataLabel="Node">
                            <PlainTextInput aria-label="Node" value={l.node} inputMode="numeric"
                                            validated={problems[`links.${l.key}`] ? "error" : "default"}
                                            onChange={(_e, v) => change({ node: v })} />
                            <Help problem={problems[`links.${l.key}`]} />
                          </Td>
                          <Td dataLabel="Tone">{toneSelect(`tm-link-${l.key}`, l.tone, (v) => change({ tone: v }))}</Td>
                          <Td isActionCell>
                            <Button variant="link" isInline isDanger
                                    onClick={() => links(draft.links.filter((_x, j) => j !== i))}>Remove</Button>
                          </Td>
                        </Tr>
                      );
                    })}
                  </Tbody>
                </Table>
              )}
              <div>
                <Button variant="secondary" onClick={() => links([...draft.links, {
                  key: `new-${Date.now()}`, original: null, node: "", tone: current("linkunkeyct") ?? "",
                }])}>Add a node</Button>
              </div>
              <Help>Plays this tone instead when a transmission from that node ends.</Help>
            </FormGroup>
            {flag("nounkeyct", "No courtesy tones at all")}
            {flag("nolocallinkct", "Use the not-linked tone when only nodes on this server are linked")}
          </Form>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>Tones</CardTitle>
        <CardBody>
          <div className="asl-stack">
            <StanzaNote stanza={t.telemetry} number={node.number} what="tones" />
            <Content component="p" className="asl-sub">
              <code>|t(tone 1,tone 2,ms,amplitude)</code> plays tones (0 for no second tone; both 0 for a pause), and
              groups follow one another. <code>|m</code> sends Morse code; anything else is a sound file. Empty is
              silent. The <a href={BUILDER} target="_blank" rel="noreferrer">telemetry builder</a> helps make tones.
            </Content>
            <Table aria-label="Tones" variant="compact">
              <Thead>
                <Tr><Th width={20}>Name</Th><Th>Value</Th></Tr>
              </Thead>
              <Tbody>
                {t.telemetry.tones.map((x) => {
                  const v = draft.tones[x.name];
                  const p = problems[`tones.${x.name}`];
                  return (
                    <Tr key={x.name}>
                      <Td dataLabel="Name">
                        <code>{x.name}</code>
                        {x.description && <div className="asl-sub">{x.description}</div>}
                      </Td>
                      <Td dataLabel="Value">
                        <PlainTextInput aria-label={`${x.name} value`} value={v ?? x.fallback ?? ""}
                                        placeholder={x.fallback === null ? "Not defined: nothing plays" : undefined}
                                        validated={p ? "error" : "default"} onChange={(_e, nv) => tone(x.name, nv)} />
                        <Help problem={p}>
                          <Source s={x} v={v} where={`in [${stanzaFor(t.telemetry, x, v)}]`}
                                  reset={() => tone(x.name, null)} show={(f) => f || "silent"} />
                        </Help>
                      </Td>
                    </Tr>
                  );
                })}
                {draft.added.map((n) => {
                  const p = problems[`tones.${n}`];
                  return (
                    <Tr key={n}>
                      <Td dataLabel="Name"><code>{n}</code> <Label color="orange" isCompact>New</Label></Td>
                      <Td dataLabel="Value">
                        <PlainTextInput aria-label={`${n} value`} value={draft.tones[n] ?? ""} validated={p ? "error" : "default"}
                                        onChange={(_e, nv) => tone(n, nv)} />
                        <Help problem={p}>
                          <Button variant="link" isInline isDanger onClick={() => {
                            const { [n]: _gone, ...rest } = draft.tones;
                            set({ ...draft, tones: rest, added: draft.added.filter((a) => a !== n) });
                          }}>Remove</Button>
                        </Help>
                      </Td>
                    </Tr>
                  );
                })}
              </Tbody>
            </Table>
            <Form onSubmit={(e) => {
              e.preventDefault();
              const n = newName.trim();
              if (!n || nameProblem) return;
              set({ ...draft, added: [...draft.added, n], tones: { ...draft.tones, [n]: "" } });
              setNewName("");
            }}>
              <div className="asl-form-row">
                <FormGroup label="New tone name" fieldId="tm-new-tone">
                  <PlainTextInput id="tm-new-tone" value={newName} onChange={(_e, v) => setNewName(v)}
                                  validated={nameProblem ? "error" : "default"} />
                  <Help problem={nameProblem}>For example ct10. Courtesy tones can then use it.</Help>
                </FormGroup>
              </div>
              <div><Button type="submit" variant="secondary" isDisabled={!newName.trim() || !!nameProblem}>Add a tone</Button></div>
            </Form>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>Morse code</CardTitle>
        <CardBody>
          <div className="asl-stack">
            <StanzaNote stanza={t.morse} number={node.number} what="Morse code settings" />
            <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
              {MORSE.map(({ key, label, unit, hint }) => {
                const s = t.morse.settings[key as keyof TelemetryStatus["morse"]["settings"]];
                const v = draft.morse[key];
                const p = problems[`morse.${key}`];
                return (
                  <FormGroup key={key} label={unit ? `${label} (${unit})` : label} fieldId={`tm-morse-${key}`}>
                    <PlainTextInput id={`tm-morse-${key}`} value={v ?? s.fallback ?? ""} inputMode="numeric"
                                    validated={p ? "error" : "default"} onChange={(_e, nv) => morse(key, nv)} />
                    <Help problem={p}>
                      {hint} <Source s={s} v={v} where={`in [${stanzaFor(t.morse, s, v)}]`}
                                     reset={() => morse(key, null)} />
                    </Help>
                  </FormGroup>
                );
              })}
            </Form>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
