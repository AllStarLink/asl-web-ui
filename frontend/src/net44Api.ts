import { del, get, post, request } from "./api";

export type Net44Zone = { services: string[]; ports: string[]; interfaces: string[] };

export type Net44Tunnel = {
  latest_handshake: number | null;
  rx_bytes: number | null;
  tx_bytes: number | null;
  endpoint: string | null;
  now: number;
};

export type Net44Mode = "full" | "split";

export type Net44Connection = {
  id: string | null;
  interface: string | null;
  zone: string | null;
  autoconnect: boolean;
  address: string | null;
  mtu: number | null;
  endpoint: string | null;
  peer_public_key: string | null;
  keepalive: number | null;
  public_key: string | null;
  mode: Net44Mode;
  routes: string[];
  ipv6: string | null;
  state: string | null;
  tunnel: Net44Tunnel | null;
  active_zone: string | null;
};

export type Net44Legacy = {
  config: string | null;
  unit: string;
  enabled: boolean;
  active: boolean;
  interface: string;
  zone: string | null;
};

export type Net44Status =
  | { available: false; reason: string; message: string }
  | {
      available: true;
      zone_name: string;
      interface: string;
      zone: Net44Zone | null;
      connection: Net44Connection | null;
      legacy: Net44Legacy | null;
      checkpoint: { seconds_left: number } | { rolled_back: true } | null;
      issues: string[];
      asterisk: { iax_port: number; echolink: boolean; voter_port: number | null };
      selection: { echolink: boolean; rtcm: boolean };
      expected_zone: { services: string[]; ports: string[] };
      zone_current: boolean;
    };

export type Net44Ready = Extract<Net44Status, { available: true }>;

export type Net44Setup = { status: Net44Ready; notes: string[] };

export type Net44Check = {
  public_ip: string | null;
  public_ip_on_44net: boolean;
  public_ip_error: string | null;
  registrations: { node: string; perceived: string; state: string; on_44net: boolean }[];
  registrations_error: string | null;
};

export const net44Status = () => get<Net44Status>("net44");
export const setNet44Zone = (echolink: boolean, rtcm: boolean) =>
  request<Net44Ready>("PUT", "net44/zone", { echolink, rtcm });
export const configureNet44 = (config: string, privateKey: string, mode: Net44Mode) =>
  post<Net44Setup>("net44/connection", { config, private_key: privateKey || undefined, mode });
export const migrateNet44 = () => post<Net44Setup>("net44/migrate");
export const setNet44Mode = (mode: Net44Mode) => request<Net44Ready>("PUT", "net44/mode", { mode });
export const startNet44 = () => post<Net44Ready>("net44/start");
export const confirmNet44 = () => post<Net44Ready>("net44/confirm");
export const stopNet44 = () => post<Net44Ready>("net44/stop");
export const removeNet44 = (deleteZone: boolean) => del<Net44Ready>(`net44${deleteZone ? "?delete_zone=1" : ""}`);
export const checkNet44 = () => get<Net44Check>("net44/check");
