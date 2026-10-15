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

export type FileContent = {
  name: string;
  content: string;
  hash: string;
  owner: string | null;
  writable: boolean;
  utf8: boolean;
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
export const readFile = (name: string) => get<FileContent>(`config/files/${encodeURIComponent(name)}`);
export const checkFile = (name: string, content: string) =>
  post<{ findings: Finding[]; counts: Counts }>(`config/files/${encodeURIComponent(name)}/check`, { content });
export const planFile = (name: string, content: string, baseHash: string) =>
  post<Plan>(`config/files/${encodeURIComponent(name)}/plan`, { content, base_hash: baseHash });
export const applyPlan = (id: string, confirmErrors = false) =>
  post<{ applied: boolean; snapshot: string }>(`changes/${encodeURIComponent(id)}/apply`, { confirm_errors: confirmErrors });
