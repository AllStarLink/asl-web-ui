import { useEffect, useState } from "react";

// Hash routing (#/overview, #/asterisk/console): needs no server rewrites,
// so it works the same behind Apache, nginx and --dev.
export function useRoute(): string {
  const read = () => window.location.hash.replace(/^#\/?/, "") || "overview";
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function go(route: string): void {
  window.location.hash = `#/${route}`;
}
