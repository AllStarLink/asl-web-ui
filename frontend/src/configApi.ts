import { get, post } from "./api";

export type Finding = {
  severity: "error" | "warning" | "info";
  code: string;
  file: string;
  line: number | null;
  message: string;
  why: string;
};

export type Counts = { error: number; warning: number; info: number };

export type FileSummary = {
  name: string;
  purpose: string;
  exists: boolean;
  owner: string | null;
  writable: boolean;
  utf8: boolean;
  modified: number | null;
  counts: Counts | null;
};

// Every file under /etc/asterisk. read_by: "Asterisk" for a top-level .conf
// file, else the files that #include it (empty: Asterisk does not read it).
export type TreeEntry = {
  name: string;
  size: number;
  modified: number;
  main: boolean;
  owner: string | null;
  writable: boolean;
  link: string | null;
  read_by: string[];
};

export type SystemFile = { path: string; size: number; modified: number; owner: string; writable: boolean; readable: boolean };
export type SystemFiles = { allmon3: SystemFile[] | null; sa818: SystemFile | null };

export type FileContent = {
  name: string;
  path: string;
  content: string;
  hash: string;
  owner: string | null;
  writable: boolean;
  utf8: boolean;
  read_by: string[] | null; // null: Asterisk reads it by name
  findings: Finding[];
};

export type Plan = {
  id: string;
  diff: string;
  unchanged: boolean;
  stale: boolean;
  findings: Finding[];
  counts: Counts;
};

export const listFiles = () => get<{ files: FileSummary[] }>("config/files");
export const listTree = () => get<{ dir: string; files: TreeEntry[]; truncated: boolean }>("config/tree");
export const listSystemFiles = () => get<SystemFiles>("config/system-files");
export const readFile = (name: string) => get<FileContent>(`config/files/${encodeURIComponent(name)}`);
export const checkFile = (name: string, content: string) =>
  post<{ findings: Finding[]; counts: Counts }>(`config/files/${encodeURIComponent(name)}/check`, { content });
export const planFile = (name: string, content: string, baseHash: string) =>
  post<Plan>(`config/files/${encodeURIComponent(name)}/plan`, { content, base_hash: baseHash });
export const applyPlan = (id: string, confirmErrors = false) =>
  post<{ applied: boolean; snapshot: string }>(`changes/${encodeURIComponent(id)}/apply`, { confirm_errors: confirmErrors });
