import { del, get, post, request } from "./api";
import { Started } from "./backupsApi";

export type CertInfo = {
  subject: string | null;
  issuer: string | null;
  starts: string | null;
  expires: string | null;
  names: string[];
  ips: string[];
  server_auth: boolean;
  fingerprint: string | null;
  lifetime_days: number | null;
  staging: boolean;
  self_signed: boolean;
  // Why Apple's devices cannot trust it even when told to: "no_san", "no_server_auth", "too_long".
  apple_problems: string[];
};

export type HttpsStatus = {
  apache: boolean;
  packages: boolean;
  // "external": another package (the ASL3 appliance) owns Apache's sites and the HTTP redirect;
  // asl-web-ui only supplies the certificate, in /etc/asl-web-ui/apache-tls.conf.
  vhosts?: "own" | "external";
  listening_443?: boolean;
  timer?: string;
  site?: { domains: string[]; redirect: boolean; cert: string | null } | null;
  site_enabled?: boolean;
  served?: CertInfo | null;
  certificate?: CertInfo | null;
  renewal?: { server: string | null; staging: boolean; authenticator: string | null; renew_hook: string | null } | null;
  // Cockpit (port 9090): "uses" is the certificate file it picks in /etc/cockpit/ws-certs.d
  // (null: its own self-signed one); "letsencrypt" when that is the Let's Encrypt certificate.
  cockpit?: { installed: boolean; uses?: string | null; letsencrypt?: boolean; hook?: boolean };
  // The ASL3 appliance's asl3-self-signed-cert is installed, so a new self-signed certificate can be made.
  self_signed_tool?: boolean;
};

export type CertificateOrder = {
  domains: string[];
  email: string;
  agree_tos: boolean;
  redirect: boolean;
};

export const httpsStatus = () => get<HttpsStatus>("https");
export const installCertbot = () => post<Started>("https/install");
export const enableListener = () => post<Started>("https/listener");
export const obtainCertificate = (order: CertificateOrder) => post<Started>("https/certificate", order);
export const setRedirect = (redirect: boolean) => request<{ redirect: boolean }>("PUT", "https/redirect", { redirect });
export const cockpitCertificate = () => post<{ cockpit: boolean }>("https/cockpit");
export const renewTest = () => post<Started>("https/renew-test");
export const removeHttps = (deleteCertificate: boolean) =>
  del<{ removed: boolean }>(`https${deleteCertificate ? "?delete_certificate=1" : ""}`);
export const renewSelfSigned = () => post<Started>("https/self-signed");
// The certificate this browser is served, to save and trust; relative to the page, like the API.
export const CERTIFICATE_DOWNLOAD = "api/v1/https/certificate.crt";
