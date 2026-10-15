import { useCallback, useEffect, useState } from "react";
import { Bullseye, Spinner } from "@patternfly/react-core";

import { ApiError, get, post, Session, setCsrfToken, SystemInfo } from "./api";
import { AsteriskPage } from "./AsteriskPage";
import { Backups } from "./Backups";
import { ConfigEditor } from "./ConfigEditor";
import { ConfigFiles } from "./ConfigFiles";
import { Login } from "./Login";
import { NodePage } from "./NodePage";
import { Nodes } from "./Nodes";
import { Overview } from "./Overview";
import { Shell } from "./Shell";
import { useRoute } from "./useRoute";
import { useStatus } from "./useStatus";

type Auth = { kind: "loading" } | { kind: "insecure" } | { kind: "anonymous" } | { kind: "user"; session: Session };

function Authenticated({ session, onLogout, onEnded }: { session: Session; onLogout: () => void; onEnded: () => void }) {
  const route = useRoute();
  const { status } = useStatus(onEnded);
  const [system, setSystem] = useState<SystemInfo | null>(null);

  useEffect(() => {
    get<SystemInfo>("system").then(setSystem, () => setSystem(null));
  }, []);

  const [base, sub, third] = route.split("/");
  let page;
  if (base === "nodes" && sub) page = <NodePage key={sub} number={sub} tab={third ?? "general"} status={status} />;
  else if (base === "nodes") page = <Nodes status={status} />;
  else if (base === "backups") page = <Backups tab={sub ?? "local"} />;
  else if (base === "asterisk") page = <AsteriskPage status={status} tab={sub ?? "status"} />;
  else if (base === "config" && sub) page = <ConfigEditor key={sub} name={decodeURIComponent(sub)} />;
  else if (base === "config") page = <ConfigFiles />;
  else page = <Overview status={status} system={system} />;
  return (
    <Shell user={session.user ?? ""} hostname={system?.hostname ?? ""} route={route} status={status} onLogout={onLogout}>
      {page}
    </Shell>
  );
}

export function App() {
  const [auth, setAuth] = useState<Auth>({ kind: "loading" });

  const load = useCallback(async () => {
    try {
      const session = await get<Session>("auth/session");
      setCsrfToken(session.csrf ?? null);
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
        onLogin={(session) => {
          setCsrfToken(session.csrf ?? null);
          setAuth({ kind: "user", session });
        }}
      />
    );
  }
  return <Authenticated session={auth.session} onLogout={logout} onEnded={() => void load()} />;
}
