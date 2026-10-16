import { del, get, post, request } from "./api";
import { Started } from "./backupsApi";

export type CertInfo = {
  subject: string | null;
  issuer: string | null;
  expires: string | null;
  names: string[];
  staging: boolean;
  self_signed: boolean;
};

export type HttpsStatus = {
  apache: boolean;
  packages: boolean;
  listening_443?: boolean;
  timer?: string;
  site?: { domains: string[]; redirect: boolean; cert: string | null } | null;
  site_enabled?: boolean;
  served?: CertInfo | null;
  certificate?: CertInfo | null;
  renewal?: { server: string | null; staging: boolean; authenticator: string | null; renew_hook: string | null } | null;
};

export type CertificateOrder = {
  domains: string[];
  email: string;
  agree_tos: boolean;
  staging: boolean;
  redirect: boolean;
};

export const httpsStatus = () => get<HttpsStatus>("https");
export const installCertbot = () => post<Started>("https/install");
export const enableListener = () => post<Started>("https/listener");
export const obtainCertificate = (order: CertificateOrder) => post<Started>("https/certificate", order);
export const setRedirect = (redirect: boolean) => request<{ redirect: boolean }>("PUT", "https/redirect", { redirect });
export const renewTest = () => post<Started>("https/renew-test");
export const removeHttps = (deleteCertificate: boolean) =>
  del<{ removed: boolean }>(`https${deleteCertificate ? "?delete_certificate=1" : ""}`);
