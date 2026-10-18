// Small client for the asl-web-ui API. Paths are relative to the page, so the
// same build works under /asl-web-ui/ (Apache, nginx) and at / (--dev).

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public data: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function csrfHeader(): Record<string, string> {
  return csrfToken ? { "X-CSRF-Token": csrfToken } : {};
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (csrfToken && method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  const resp = await fetch(`api/v1/${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  let data: unknown = null;
  try {
    data = await resp.json();
  } catch {
    // Non-JSON error page from the web server.
  }
  if (!resp.ok && resp.status !== 429) {
    const err = (data ?? {}) as { error?: string; message?: string };
    throw new ApiError(
      resp.status,
      err.error ?? "http_error",
      err.message ?? `The server answered with HTTP ${resp.status}.`,
      (data ?? {}) as Record<string, unknown>,
    );
  }
  return data as T;
}

export const get = <T>(path: string) => request<T>("GET", path);
export const post = <T>(path: string, body: unknown = {}) => request<T>("POST", path, body);
export const del = <T>(path: string) => request<T>("DELETE", path);

// The message to show for a failed call.
export function message(err: unknown): string {
  return err instanceof ApiError ? err.message : "The server could not be reached.";
}

// WebSocket URL for an API path, relative to the page.
export function wsUrl(path: string): string {
  const url = new URL(`api/v1/${path}`, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

// Open a WebSocket to an API path. Safari does not reliably send the session
// cookie with WebSocket handshakes, so a one-time ticket from an ordinary
// (cookie-carrying) request goes in the URL. Rejects with ApiError when the
// session has ended (status 401). Extra query parameters go in params.
export async function openSocket(path: string, params: Record<string, string> = {}): Promise<WebSocket> {
  const { ticket } = await post<{ ticket: string }>("auth/ws-ticket");
  const query = new URLSearchParams({ ...params, ticket });
  return new WebSocket(`${wsUrl(path)}?${query.toString()}`);
}

// ---- types ---------------------------------------------------------------

export type Session = {
  user: string | null;
  csrf?: string;
  keep?: boolean;
  recent_auth_until?: number;
};

export type LoginStep = {
  state: "prompt" | "success" | "failure";
  id?: string;
  prompt?: { echo: boolean; text: string };
  messages: { kind: "info" | "error"; text: string }[];
  message?: string;
  retry_after?: number;
  session?: Session;
};

export type Registration = {
  host: string;
  username: string;
  perceived: string;
  refresh: number | null;
  state: string;
};

export type Status = {
  collected_at: number;
  asterisk: {
    state: string;
    substate: string;
    since: string;
    reachable: boolean;
    uptime: number | null;
    last_reload: number | null;
  };
  versions: { asterisk?: string | null; app_rpt?: string | null };
  nodes: { node: string; private: boolean; registration: string | null }[];
  registrations: Registration[];
  iax_registrations: Registration[];
  config: {
    changed: string[];
    rpt_errors: number;
    rpt_first_error: { line: number | null; file: string; message: string } | null;
  };
  error: string | null;
};

export type SystemInfo = {
  hostname: string;
  os: string;
  kernel: string;
  uptime: number | null;
  asl_web_ui: string;
};
