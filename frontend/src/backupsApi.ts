import { ApiError, csrfHeader, del, get, post, request } from "./api";

export type LocalBackup = { name: string; size: number; modified: number };
export type BackupList = {
  local: LocalBackup[];
  // sync: a node whose registration password savenode.conf could take (nodes/plan "savenode").
  cloud: { configured: boolean; node: string | null; reason: string | null; sync: string | null };
  cloud_max: number;
  server: string;
  directory: string;
};
export type Contents = { files: string[]; skipped: { name: string; reason: string }[]; asl3: boolean };
export type JobState = {
  title: string;
  lines: string[];
  next: number;
  done: boolean;
  ok: boolean;
  result: Record<string, unknown> | null;
  error: string | null;
  code: string | null;
};
export type Started = { job: string };
export type IncludeList = { content: string; hash: string; exists: boolean };
export type Credentials = { node?: string; password?: string };

const enc = encodeURIComponent;

export const listBackups = () => get<BackupList>("backups");
export const createBackup = (upload: boolean) => post<Started>("backups", { upload });
export const backupContents = (name: string) => get<Contents>(`backups/local/${enc(name)}/contents`);
export const restoreBackup = (name: string) => post<Started>(`backups/local/${enc(name)}/restore`, {});
export const uploadBackup = (name: string) => post<Started>(`backups/local/${enc(name)}/upload`, {});
export const deleteBackup = (name: string) => del<{ deleted: string }>(`backups/local/${enc(name)}`);
export const downloadUrl = (name: string) => `api/v1/backups/local/${enc(name)}/download`;
export const cloudList = (c: Credentials) => post<{ node: string; backups: string[] }>("backups/cloud/list", c);
export const cloudFetch = (name: string, restore: boolean, c: Credentials) =>
  post<Started>("backups/cloud/fetch", { name, restore, ...c });
export const getIncludeList = () => get<IncludeList>("backups/include-list");
export const putIncludeList = (content: string, hash: string) =>
  request<{ hash: string }>("PUT", "backups/include-list", { content, hash });
export const factoryReset = () => post<Started>("backups/factory-reset", {});
export const jobState = (id: string, from: number) => get<JobState>(`jobs/${enc(id)}?from=${from}`);
export const fixOwnership = (files: string[]) => post<{ fixed: string[] }>("config/fix-ownership", { files });

export async function importBackup(file: File): Promise<{ name: string }> {
  const form = new FormData();
  form.append("file", file, file.name);
  return upload<{ name: string }>("backups/import", form);
}

// multipart/form-data upload (the JSON helpers set their own content type).
async function upload<T>(path: string, form: FormData): Promise<T> {
  const resp = await fetch(`api/v1/${path}`, {
    method: "POST",
    body: form,
    headers: { Accept: "application/json", ...csrfHeader() },
    credentials: "same-origin",
  });
  let data: Record<string, unknown> = {};
  try {
    data = await resp.json();
  } catch {
    // web server error page
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, (data.error as string) ?? "http_error",
      (data.message as string) ?? (resp.status === 413 ? "The file is too large." : `The server answered with HTTP ${resp.status}.`), data);
  }
  return data as T;
}

export function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
