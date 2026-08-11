import { abilityPercent } from '@/lib/format';

export function AbilityBars({
  scores,
  toneByScore = true,
  className,
}: {
  scores: Record<string, number>;
  toneByScore?: boolean;
  className?: string;
}) {
  const sorted = Object.entries(scores)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);
  const tone = (score: number) => {
    if (!toneByScore) return 'bg-accent/80';
    if (score >= 7) return 'bg-ok';
    if (score >= 5) return 'bg-accent/80';
    if (score >= 3) return 'bg-warn';
    return 'bg-err';
  };
  return (
    <div className={className}>
      {sorted.map(([label, score]) => (
        <div key={label} className="mb-3 last:mb-0">
          <div className="mb-1 flex items-center justify-between">
            <span className="font-mono text-[11px] text-ink-secondary">{label}</span>
            <span className="font-mono text-xs text-ink mono-num">{score.toFixed(1)}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface">
            <div
              className={`h-full rounded-full transition-[width] duration-500 ${tone(score)}`}
              style={{ width: `${abilityPercent(score)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
