import { useCallback, useEffect, useRef, useState } from "react";

// Hash routing (#/overview, #/asterisk/console): needs no server rewrites,
// so it works the same behind Apache, nginx and --dev.

const read = () => window.location.hash.replace(/^#\/?/, "") || "overview";

// A page with unsaved changes installs a guard: true for the routes that
// keep them (such as its own tabs). Leaving for any other route asks first.
let guard: ((route: string) => boolean) | null = null;
let forced = false;

export function useLeaveGuard(stays: ((route: string) => boolean) | null): void {
  useEffect(() => {
    guard = stays;
    return () => {
      if (guard === stays) guard = null;
    };
  }, [stays]);
}

// The current route, the route the user tried to leave for (while a guard
// holds them back), and the answer to "leave anyway?".
export function useRoute(): [string, string | null, (leave: boolean) => void] {
  const [route, setRoute] = useState(read);
  const [leaving, setLeaving] = useState<string | null>(null);
  const current = useRef(route);
  useEffect(() => {
    const onChange = () => {
      const next = read();
      if (!forced && guard && !guard(next)) {
        // The address has already changed: put it back without another hashchange.
        history.replaceState(history.state, "", `#/${current.current}`);
        setLeaving(next);
        return;
      }
      forced = false;
      current.current = next;
      setRoute(next);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const answer = useCallback((leave: boolean) => {
    setLeaving(null);
    if (leave && leaving !== null) go(leaving, true);
  }, [leaving]);
  return [route, leaving, answer];
}

// force: leave even if the page has unsaved changes (they were just saved,
// or the user agreed to lose them).
export function go(route: string, force = false): void {
  if (window.location.hash === `#/${route}`) return;
  forced = force;
  window.location.hash = `#/${route}`;
}
