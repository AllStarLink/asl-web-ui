import { Allmon3Applied, Allmon3File, Allmon3Finding, Allmon3Plan, Allmon3Unchanged } from "./allmon3Api";
import { get, post, request } from "./api";

// /etc/sa818.conf's keys, as sa818-menu names them.
export type SA818Settings = {
  CURRENT_BAND: "VHF" | "UHF";
  CURRENT_BANDWIDTH: "Narrow" | "Wide";
  CURRENT_FREQ_RX: string;
  CURRENT_FREQ_TX: string;
  CURRENT_SQUELCH: string;
  CURRENT_VOLUME: string;
  CURRENT_TONE: "None" | "CTCSS" | "DCS";
  CURRENT_CTCSS_RX: string;
  CURRENT_CTCSS_TX: string;
  CURRENT_DCS_RX: string;
  CURRENT_DCS_TX: string;
  CURRENT_TAIL_TONE: "Opened" | "Closed";
  CURRENT_EMPHASIS: "Enabled" | "Disabled";
  CURRENT_FILTER_HIGH_PASS: "Enabled" | "Disabled";
  CURRENT_FILTER_LOW_PASS: "Enabled" | "Disabled";
  CURRENT_PORT: string;
  CURRENT_SPEED: string;
};

export type SA818State = {
  saved: boolean;
  settings: SA818Settings;
  ports: string[];
  tool: boolean;
  choices: { ctcss: string[]; dcs: string[]; speeds: string[]; bands: Record<string, [number, number]> };
};

export type SA818Result = { saved: boolean; programmed: boolean; log: string[]; settings: SA818Settings };
export type SA818Version = { ok: boolean; firmware: string | null; log: string[] };

export const readSA818 = () => get<SA818State>("sa818");
export const applySA818 = (settings: SA818Settings) => request<SA818Result>("PUT", "sa818", { settings });
export const programSA818 = () => post<SA818Result>("sa818/program");
export const sa818Version = () => post<SA818Version>("sa818/version");

// /etc/sa818.conf as text (Manual Config Edit); same shapes as Allmon3's files.
export const readSA818File = () => get<Allmon3File>("sa818/file");
export const checkSA818File = (content: string) => post<{ findings: Allmon3Finding[] }>("sa818/file/check", { content });
export const planSA818File = (content: string, hash: string) =>
  post<Allmon3Plan | Allmon3Unchanged>("sa818/file/plan", { content, hash });
export const applySA818FilePlan = (id: string, confirmErrors = false) =>
  post<Allmon3Applied>(`sa818/file/plans/${encodeURIComponent(id)}/apply`, { confirm_errors: confirmErrors });
