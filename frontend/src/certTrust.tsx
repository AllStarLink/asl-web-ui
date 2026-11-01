import { useSyncExternalStore } from "react";
import { Button, Content, Title } from "@patternfly/react-core";

import { onSocketFailures, socketFailuresInARow } from "./api";
import { CERTIFICATE_DOWNLOAD } from "./httpsApi";

// Self-signed certificates and Safari (issue #46). Safari refuses
// WebSockets to a server whose certificate the device does not trust, even
// after the user accepted the page's warning; ordinary requests still work.
// The fix is to trust the certificate on the device, which Apple's devices
// allow only for a certificate that keeps Apple's rules
// (https://support.apple.com/en-us/103769).

// After this many sockets in a row fail to open, the page says why.
export const SOCKET_FAILURES_SHOWN = 3;

// Days before a self-signed certificate expires that the pages warn.
export const EXPIRY_WARNING_DAYS = 30;

export function useSocketTrouble(): boolean {
  const failures = useSyncExternalStore(onSocketFailures, socketFailuresInARow);
  return failures >= SOCKET_FAILURES_SHOWN && location.protocol === "https:";
}

type Named = { names: string[]; ips: string[] };

// Whether the certificate names HOST, as a browser checks it.
export function namesHost(cert: Named, host: string): boolean {
  const h = host.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  return cert.ips.includes(h) || cert.names.some((raw) => {
    const n = raw.toLowerCase();
    if (n === h) return true;
    // *.example.org covers one label: a.example.org, not a.b.example.org.
    return n.startsWith("*.") && h.endsWith(n.slice(1)) && !h.slice(0, h.length - n.length + 1).includes(".");
  });
}

const PROBLEMS: Record<string, string> = {
  no_san: "Its names are only in the subject; Apple needs them in a subjectAltName.",
  no_server_auth: "It is not marked for use by TLS servers (extendedKeyUsage serverAuth).",
  too_long: "It is valid for longer than Apple's limit of 825 days.",
  wrong_name: "It does not name the address this browser uses.",
};

// Why Macs, iPhones and iPads cannot trust the certificate for HOST, as sentences.
export function appleProblems(cert: Named & { apple_problems: string[] }, host: string): string[] {
  const codes = [...cert.apple_problems];
  if (!codes.includes("no_san") && !namesHost(cert, host)) codes.push("wrong_name");
  return codes.map((c) => PROBLEMS[c] ?? c);
}

// Whole days until EXPIRES (negative once it has passed), or null.
export function daysLeft(expires: string | null | undefined): number | null {
  if (!expires) return null;
  const t = new Date(expires).getTime();
  return Number.isNaN(t) ? null : Math.floor((t - Date.now()) / 86400000);
}

// How to trust the certificate on a Mac, iPhone or iPad.
export function TrustSteps({ fingerprint, subject }: { fingerprint?: string | null; subject?: string | null }) {
  const name = subject?.replace(/^CN\s*=\s*/, "") || "this server";
  return (
    <div className="asl-stack">
      <div>
        <Button component="a" variant="secondary" href={CERTIFICATE_DOWNLOAD} download>
          Download the certificate
        </Button>
      </div>
      <Title headingLevel="h4">On a Mac</Title>
      <Content component="ol">
        <Content component="li">Download the certificate and open the downloaded file. Keychain Access adds it to the login keychain.</Content>
        <Content component="li">
          In Keychain Access, double-click the certificate named <b>{name}</b>, open <b>Trust</b>, and set{" "}
          <b>When using this certificate</b> to <b>Always Trust</b>.
        </Content>
        <Content component="li">Quit Safari completely and open it again.</Content>
      </Content>
      <Title headingLevel="h4">On an iPhone or iPad</Title>
      <Content component="ol">
        <Content component="li">Open this page in Safari, download the certificate, and allow the configuration profile.</Content>
        <Content component="li">In Settings, open <b>Profile Downloaded</b> and install it.</Content>
        <Content component="li">
          If <b>Settings › General › About › Certificate Trust Settings</b> lists it, turn on full trust for it.
        </Content>
      </Content>
      {fingerprint && (
        <Content component="p" className="asl-sub">
          Before trusting it, check that its SHA-256 fingerprint is <code className="asl-fingerprint">{fingerprint}</code>
        </Content>
      )}
      <Content component="p" className="asl-sub">
        Each new certificate has to be trusted again, on every device.
      </Content>
    </div>
  );
}
