import { del, get, post, request } from "./api";

export type Allmon3Finding = { line: number | null; severity: "error" | "warning" | "info"; message: string };

export type Allmon3Overview = {
  installed: boolean;
  service: { active: string | null; sub: string | null; since: string | null; enabled: string | null };
  url: string;
  nodes: string[];
  files: { name: string; description: string; exists: boolean; optional: boolean; errors: number; warnings: number }[];
};

export type Allmon3File = {
  name: string;
  path: string;
  exists: boolean;
  optional: boolean;
  content: string;
  hash: string;
  findings: Allmon3Finding[];
};

export type Allmon3Node = {
  node: string;
  line: number | null;
  host?: string;
  port?: string;
  user?: string;
  multinodes?: string;
  voters?: string;
  pollinterval?: string;
  vpollinterval?: string;
  retryinterval?: string;
  retrycount?: string;
  iframepre?: string;
  iframepost?: string;
  pass_set: boolean;
  pass_matches_ami: boolean;
  local_host: boolean;
};

export type Allmon3Nodes = {
  nodes: Allmon3Node[];
  local: { number: string; listed: boolean }[];
  ami_users: string[];
  ami_port: string;
  findings: Allmon3Finding[];
};

export type Allmon3Plan = {
  id: string;
  name: string;
  action: string;
  diff: string;
  created: boolean;
  findings: Allmon3Finding[];
};
export type Allmon3Unchanged = { unchanged: true; findings: Allmon3Finding[] };
export type Allmon3Applied = { hash?: string; warnings: string[] };

export type Allmon3Users = {
  users: { name: string; nodes: string[] | null }[];
  orphan_restrictions: string[];
  nodes: string[];
};

export const WEB_KEYS = [
  "CONFIG_HEADER_TITLE", "CONFIG_HEADER_LOGO", "CONFIG_MENU_SINGLE_TARGET", "HOME_BUTTON_URL", "HTTP_PORT",
  "WS_PORT_START", "WS_BIND_ADDR",
] as const;
export type WebKey = (typeof WEB_KEYS)[number];

const file = (name: string) => `allmon3/files/${encodeURIComponent(name)}`;

export const allmon3Overview = () => get<Allmon3Overview>("allmon3");
export const allmon3Service = (action: "start" | "stop" | "restart") =>
  post<{ active: string | null }>(`allmon3/service/${action}`);
export const readAllmon3File = (name: string) => get<Allmon3File>(file(name));
export const checkAllmon3File = (name: string, content: string) =>
  post<{ findings: Allmon3Finding[] }>(`${file(name)}/check`, { content });
export const planAllmon3File = (name: string, content: string, hash: string) =>
  post<Allmon3Plan | Allmon3Unchanged>(`${file(name)}/plan`, { content, hash });
export const deleteAllmon3File = (name: string, hash: string) =>
  del<Allmon3Applied>(`${file(name)}?hash=${encodeURIComponent(hash)}`);
export const allmon3Nodes = () => get<Allmon3Nodes>("allmon3/nodes");
export const planAllmon3Nodes = (body: Record<string, unknown>) =>
  post<Allmon3Plan | Allmon3Unchanged>("allmon3/nodes/plan", body);
export const allmon3Web = () => get<{ values: Partial<Record<WebKey, string>>; findings: Allmon3Finding[] }>("allmon3/web");
export const planAllmon3Web = (values: Partial<Record<WebKey, string | null>>) =>
  post<Allmon3Plan | Allmon3Unchanged>("allmon3/web/plan", { values });
export const applyAllmon3Plan = (id: string, confirmErrors = false) =>
  post<Allmon3Applied>(`allmon3/plans/${encodeURIComponent(id)}/apply`, { confirm_errors: confirmErrors });
export const allmon3Users = () => get<Allmon3Users>("allmon3/users");
export const setAllmon3Password = (user: string, password: string) =>
  post<{ created: boolean; warnings: string[] }>("allmon3/users", { user, password });
export const deleteAllmon3User = (user: string) => del<Allmon3Applied>(`allmon3/users/${encodeURIComponent(user)}`);
export const setAllmon3UserNodes = (user: string, nodes: string[] | null) =>
  request<Allmon3Applied>("PUT", `allmon3/users/${encodeURIComponent(user)}/nodes`, { nodes });
