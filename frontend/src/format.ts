// Human-readable durations, e.g. "3 days, 5 hours".
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const units: [string, number][] = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  const parts: string[] = [];
  let rest = Math.floor(seconds);
  for (const [name, size] of units) {
    const n = Math.floor(rest / size);
    if (n > 0) {
      parts.push(`${n} ${name}${n === 1 ? "" : "s"}`);
      rest -= n * size;
    }
    if (parts.length === 2) break;
  }
  return parts.length ? parts.join(", ") : "less than a minute";
}
