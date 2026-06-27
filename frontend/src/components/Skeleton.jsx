// Lightweight shimmer placeholders shown while data loads.
export function Skeleton({ className = "" }) {
  return <div className={`bg-ink-700/70 rounded animate-pulse ${className}`} />;
}

export function SkeletonRow({ cols = 5 }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="td"><Skeleton className="h-4 w-full max-w-[120px]" /></td>
      ))}
    </tr>
  );
}

export function SkeletonStat() {
  return (
    <div className="card">
      <Skeleton className="h-3 w-24 mb-3" />
      <Skeleton className="h-8 w-32" />
    </div>
  );
}
