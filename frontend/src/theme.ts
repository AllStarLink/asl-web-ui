// Follow the browser's light/dark preference, as Cockpit does.
export function followSystemTheme(): void {
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const apply = () => document.documentElement.classList.toggle("pf-v6-theme-dark", query.matches);
  apply();
  query.addEventListener("change", apply);
}
