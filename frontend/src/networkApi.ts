import { get, request } from "./api";

export type NetInterface = {
  name: string;
  type: string;
  mac: string | null;
  ipv4: string[];
  ipv6: string[];
};

export type FallbackAp =
  | { available: false }
  | { available: true; enabled: boolean; active: boolean; ssid: string | null; open: boolean };

export type NetworkStatus = {
  interfaces: NetInterface[];
  fallback_ap: FallbackAp;
};

export const networkStatus = () => get<NetworkStatus>("network");
export const setFallbackAp = (enable: boolean) => request<FallbackAp>("PUT", "network/fallback-ap", { enable });

// Cockpit runs on the same host, on its own port.
export const cockpitUrl = (path: string) => `https://${window.location.hostname}:9090/${path}`;
