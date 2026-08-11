import { useId } from 'react';

const MAX_AXES = 6;

export function RadarChart({ scores, size = 280 }: { scores: Record<string, number>; size?: number }) {
  const gradId = useId();
  const entries = Object.entries(scores).slice(0, MAX_AXES);
  if (entries.length < 3) return null;

  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 42;
  const n = entries.length;
  const angleAt = (index: number) => (Math.PI * 2 * index) / n - Math.PI / 2;
  const pointAt = (index: number, ratio: number) => {
    const angle = angleAt(index);
    return [cx + Math.cos(angle) * radius * ratio, cy + Math.sin(angle) * radius * ratio] as const;
  };

  const rings = [0.25, 0.5, 0.75, 1];
  const ringPoints = rings.map((ratio) =>
    entries.map((_, index) => pointAt(index, ratio).join(',')).join(' '),
  );
  const valuePoints = entries.map(([, value], index) => pointAt(index, Math.max(0.06, value / 10)).join(',')).join(' ');

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`能力雷达：${entries.map(([label, value]) => `${label} ${value} 分`).join('；')}`}
      className="mx-auto"
    >
      <defs>
        <radialGradient id={gradId} cx="50%" cy="50%" r="60%">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.28" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.06" />
        </radialGradient>
      </defs>
      {ringPoints.map((points, index) => (
        <polygon key={index} points={points} fill="none" stroke="var(--line)" strokeWidth={1} />
      ))}
      {entries.map((_, index) => {
        const [x, y] = pointAt(index, 1);
        const [ix, iy] = pointAt(index, 0.02);
        return <line key={index} x1={ix} y1={iy} x2={x} y2={y} stroke="var(--line)" strokeWidth={1} />;
      })}
      <polygon points={valuePoints} fill={`url(#${gradId})`} stroke="var(--accent)" strokeWidth={1.5} />
      {entries.map(([label, value], index) => {
        const [x, y] = pointAt(index, 1);
        const [vx, vy] = pointAt(index, Math.max(0.06, value / 10));
        const labelPos = pointAt(index, 1.24);
        return (
          <g key={label}>
            <circle cx={vx} cy={vy} r={2.5} fill="var(--accent)" />
            <text
              x={labelPos[0]}
              y={labelPos[1]}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={10}
              fill="var(--ink-secondary)"
              fontFamily="'JetBrains Mono', Consolas, monospace"
            >
              {label}
            </text>
            <text x={x} y={y - 3} textAnchor="middle" fontSize={9} fill="var(--ink-tertiary)" fontFamily="monospace">
              {value.toFixed(1)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
