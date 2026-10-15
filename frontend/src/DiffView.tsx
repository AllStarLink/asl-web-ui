// A unified diff, colored by line.
export function DiffView({ diff }: { diff: string }) {
  const lines = diff.split("\n").filter((l, i, all) => !(i === all.length - 1 && l === ""));
  return (
    <pre className="asl-diff" aria-label="Changes">
      {lines.map((line, i) => {
        const cls = line.startsWith("+++") || line.startsWith("---") ? "file"
          : line.startsWith("@@") ? "hunk"
          : line.startsWith("+") ? "add"
          : line.startsWith("-") ? "del" : "";
        return (
          <span key={i} className={cls}>
            {line || " "}
            {"\n"}
          </span>
        );
      })}
    </pre>
  );
}
