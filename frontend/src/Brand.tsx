// The AllStarLink star and name.
export function Star({ size = 26 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <polygon points="12,1.5 14.9,8.4 22.4,8.9 16.6,13.7 18.5,21 12,17 5.5,21 7.4,13.7 1.6,8.9 9.1,8.4" fill="#f5c12e" />
    </svg>
  );
}

export function Brand({ subtitle }: { subtitle: string }) {
  return (
    <div className="asl-brand">
      <Star size={34} />
      <div>
        <b>AllStarLink</b>
        <span>{subtitle}</span>
      </div>
    </div>
  );
}
