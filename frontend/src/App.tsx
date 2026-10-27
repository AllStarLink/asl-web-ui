import { useCallback, useEffect, useState } from "react";
import { Bullseye, Button, Modal, ModalBody, ModalFooter, ModalHeader, Spinner } from "@patternfly/react-core";

import { ApiError, get, post, Session, setCsrfToken, SystemInfo } from "./api";
import { Allmon3Page } from "./Allmon3Page";
import { AsteriskPage } from "./AsteriskPage";
import { Backups } from "./Backups";
import { Diagnostics } from "./Diagnostics";
import { ConfigEditor } from "./ConfigEditor";
import { ConfigFiles } from "./ConfigFiles";
import { HardwarePage } from "./HardwarePage";
import { HttpsPage } from "./HttpsPage";
import { Login } from "./Login";
import { Net44Page } from "./Net44Page";
import { NetworkPage } from "./NetworkPage";
import { NodePage } from "./NodePage";
import { Nodes } from "./Nodes";
import { Overview } from "./Overview";
import { Allmon3Editor, SA818FileEditor } from "./SystemFileEditor";
import { Shell } from "./Shell";
import { useRoute } from "./useRoute";
import { StatusTopic, useStatus } from "./useStatus";

type Auth = { kind: "loading" } | { kind: "insecure" } | { kind: "anonymous" } | { kind: "user"; session: Session };

function Authenticated({ session, onLogout, onEnded }: { session: Session; onLogout: () => void; onEnded: () => void }) {
  const [route, leaving, answer] = useRoute();
  const [base, sub, third] = route.split("/");
  const { status } = useStatus(onEnded, topicsFor(base, sub));
  const [system, setSystem] = useState<SystemInfo | null>(null);

  useEffect(() => {
    get<SystemInfo>("system").then(setSystem, () => setSystem(null));
  }, []);

  let page;
  if (base === "nodes" && sub) page = <NodePage key={sub} number={sub} tab={third ?? "general"} status={status} />;
  else if (base === "nodes") page = <Nodes status={status} />;
  else if (base === "diagnostics") page = <Diagnostics status={status} />;
  else if (base === "backups") page = <Backups tab={sub ?? "local"} />;
  else if (base === "asterisk") page = <AsteriskPage status={status} tab={sub ?? "status"} />;
  else if (base === "allmon3" && sub === "files" && third) page = <Allmon3Editor key={third} name={decodeURIComponent(third)} />;
  else if (base === "https") page = <HttpsPage />;
  // #/sa818 was the SA818 page before it moved to Hardware.
  else if (base === "hardware" || base === "sa818") page = <HardwarePage />;
  else if (base === "network") page = <NetworkPage />;
  else if (base === "44net") page = <Net44Page />;
  else if (base === "allmon3") page = <Allmon3Page tab={sub ?? "status"} />;
  else if (base === "config" && sub === "~allmon3" && third)
    page = <Allmon3Editor key={third} name={decodeURIComponent(third)} from="config" />;
  else if (base === "config" && sub === "~sa818") page = <SA818FileEditor />;
  else if (base === "config" && sub) page = <ConfigEditor key={sub} name={decodeURIComponent(sub)} />;
  else if (base === "config") page = <ConfigFiles />;
  else page = <Overview status={status} system={system} />;
  return (
    <Shell user={session.user ?? ""} hostname={system?.hostname ?? ""} route={route} status={status} onLogout={onLogout}>
      {page}
      <Modal isOpen={leaving !== null} onClose={() => answer(false)} variant="small" aria-labelledby="leave-title">
        <ModalHeader title="Leave without saving?" labelId="leave-title" titleIconVariant="warning" />
        <ModalBody>This page has changes that are not saved. If you leave it, they are lost.</ModalBody>
        <ModalFooter>
          <Button variant="danger" onClick={() => answer(true)}>Leave and discard changes</Button>
          <Button variant="link" onClick={() => answer(false)}>Stay on this page</Button>
        </ModalFooter>
      </Modal>
    </Shell>
  );
}

// Pages that show node registrations: the overview, the node list and pages,
// and Asterisk's status tab. Others leave the server's poll to the basics.
const REGISTRATIONS: StatusTopic[] = ["registrations"];
const NONE: StatusTopic[] = [];

function topicsFor(base: string, sub: string | undefined): StatusTopic[] {
  const shows = base === "overview" || base === "nodes" || (base === "asterisk" && (sub ?? "status") === "status");
  return shows ? REGISTRATIONS : NONE;
}

export function App() {
  const [auth, setAuth] = useState<Auth>({ kind: "loading" });
  // Over plain HTTP the server answers nothing, not even its name.
  const [hostname, setHostname] = useState(location.hostname);

  const load = useCallback(async () => {
    try {
      const session = await get<Session>("auth/session");
      setCsrfToken(session.csrf ?? null);
      if (session.hostname) setHostname(session.hostname);
      setAuth(session.user ? { kind: "user", session } : { kind: "anonymous" });
    } catch (err) {
      setAuth(err instanceof ApiError && err.code === "https_required" ? { kind: "insecure" } : { kind: "anonymous" });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const logout = async () => {
    try {
      await post("auth/logout");
    } finally {
      setCsrfToken(null);
      setAuth({ kind: "anonymous" });
    }
  };

  if (auth.kind === "loading") {
    return (
      <Bullseye className="asl-fill">
        <Spinner aria-label="Loading" />
      </Bullseye>
    );
  }
  if (auth.kind !== "user") {
    return (
      <Login
        insecure={auth.kind === "insecure"}
        hostname={hostname}
        onLogin={(session) => {
          setCsrfToken(session.csrf ?? null);
          setAuth({ kind: "user", session });
        }}
      />
    );
  }
  return <Authenticated session={auth.session} onLogout={logout} onEnded={() => void load()} />;
}
