import { useEffect } from "react";

// The browser tab title: the open page, then the server ("Nodes | node40608").
export function useDocumentTitle(page: string, hostname: string): void {
  useEffect(() => {
    document.title = hostname ? `${page} | ${hostname}` : page;
  }, [page, hostname]);
}
