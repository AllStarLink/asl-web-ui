import { del, get, post } from "./api";
import { Finding } from "./configApi";

export type Reference = { kind: string; section: string | null; templates: string[]; exists: boolean };

export type NodeInfo = {
  number: string;
  private: boolean;
  file: string;
  line: number;
  templates: string[];
  callsign: string | null;
  idrecording: string | null;
  id_simple: boolean;
  duplex: number | null;
  linktolink: string;
  hangtime: number;
  statpost: boolean;
  statpost_inherited: boolean;
  rxchannel: string | null;
  interface: string | null;
  password_set: boolean;
  registered: boolean;
  // How the node registers with AllStarLink ("both" is a duplicate to fix).
  registration: "http" | "iax" | "both" | null;
  nodes_entry: string | null;
  channel_templates: string[] | null;
  references: Record<string, Reference>;
  startup: {
    macro: string | null;
    funcchar: string;
    target: string | null;
    mode: "transceive" | "monitor" | null;
    permanent: boolean;
    custom: boolean;
    permanent_available: boolean;
  };
};

export type CustomOption = {
  name: string;
  description: string;
  files: string[];
  types: string[];
  duplex: number | null;
  interface: string | null;
  device: boolean;
};

export type CustomStatus = {
  state: "unavailable" | "available" | "active";
  reason: string | null;
  can_enable: boolean;
  options: CustomOption[];
  selected: string[];
};

export type Preset = { id: string; label: string; duplex: number; interface: string | null };

export type NodeList = {
  nodes: (NodeInfo & { customizations: CustomStatus["state"] })[];
  first_run: boolean;
  rpt_errors: number;
  iax_port: number;
  interfaces: { id: string; label: string }[];
  duplex: { value: number; label: string }[];
  presets: { common: Preset[]; devices: CustomOption[] };
  customize: Record<"SimpleUSB" | "USBRadio" | "other", { reason: string | null; options: CustomOption[] }>;
  private_limit: number;
};

export type VoterClient = {
  name: string;
  transmit: boolean;
  master: boolean;
  nodeemp: boolean;
  noplfilter: boolean;
  gpsid: string | null;
  prio: number | null;
  other: string[];
};

// voter.conf for an RTCM/voter node (no passwords).
export type VoterStatus = {
  configured: boolean;
  clients: VoterClient[];
  settings: Record<string, string>;
  general: Record<string, string>;
  host_password_set: boolean;
  master_elsewhere: string[];
};

export type NodeDetail = NodeInfo & { customizations: CustomStatus; voter: VoterStatus | null };

export type Note = { severity: "info" | "warning"; text: string };

export type ChangePlan = {
  id: string;
  action: string;
  files: { name: string; diff: string }[];
  notes: Note[];
  allmon3: string[];
  restart: boolean;
  tune: boolean;
  errors: Finding[];
  reauth: boolean;
};

export type Unchanged = { unchanged: true; notes: Note[] };

export type Applied = { applied: boolean; snapshot: string; warnings: string[]; restart: boolean };

export type AccessEntry = { entry: string; reason: string };
export type AccessLists = { allow: AccessEntry[]; deny: AccessEntry[]; mode: "open" | "allow" | "deny" };

export type AsteriskSettings = { iax_port: number; ami_users: string[]; ami_admin: boolean };

export const listNodes = () => get<NodeList>("nodes");
export const getNode = (n: string) => get<NodeDetail>(`nodes/${encodeURIComponent(n)}`);
// One operation ({op, ...}) or several planned as one change ({ops: [...]}).
export const planChange = (body: Record<string, unknown>) => post<ChangePlan | Unchanged>("nodes/plan", body);
export const applyChange = (id: string, confirmErrors = false) =>
  post<Applied>(`changes/${encodeURIComponent(id)}/apply`, { confirm_errors: confirmErrors });

export const getAccess = (n: string) => get<AccessLists>(`nodes/${encodeURIComponent(n)}/access`);
export const addAccess = (n: string, list: "allow" | "deny", entry: string, reason: string) =>
  post<AccessLists>(`nodes/${encodeURIComponent(n)}/access`, { list, entry, reason });
export const removeAccess = (n: string, list: string, entry: string) =>
  del<AccessLists>(`nodes/${encodeURIComponent(n)}/access/${list}/${encodeURIComponent(entry)}`);
export const clearAccess = (n: string, list: string) => del<AccessLists>(`nodes/${encodeURIComponent(n)}/access/${list}`);

export const asteriskSettings = () => get<AsteriskSettings>("asterisk/settings");
export const asteriskAction = (action: "restart" | "start" | "stop", confirmErrors = false) =>
  post<{ done: boolean }>(`asterisk/${action}`, { confirm_errors: confirmErrors });
export const systemAction = (action: "reboot" | "poweroff") => post<{ done: boolean }>(`system/${action}`, {});

export const INTERFACE_NAMES: Record<string, string> = {
  SimpleUSB: "SimpleUSB",
  USBRadio: "USBRadio",
  Voter: "RTCM / VOTER",
  Pseudo: "None (hub)",
  USRP: "USRP",
};
