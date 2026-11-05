// 12 monthly bars of work-log days (counts computed by the backend — this
// only draws them). Zero months show as a faint baseline tick.
export function Sparkline({ spark }: { spark: { month: string; days: number }[] }) {
  const max = Math.max(1, ...spark.map((s) => s.days));
  const w = 4;
  const gap = 2;
  const h = 18;
  return (
    <svg
      width={spark.length * (w + gap) - gap}
      height={h}
      viewBox={`0 0 ${spark.length * (w + gap) - gap} ${h}`}
      role="img"
      aria-label={`Work-log days per month: ${spark.map((s) => `${s.month} ${s.days}`).join(", ")}`}
      className="shrink-0"
    >
      {spark.map((s, i) => {
        const bh = s.days ? Math.max(3, Math.round((s.days / max) * h)) : 1;
        return (
          <rect
            key={s.month}
            x={i * (w + gap)}
            y={h - bh}
            width={w}
            height={bh}
            rx={1}
            className={s.days ? "fill-accent" : "fill-line-strong"}
          >
            <title>{`${s.month}: ${s.days} day${s.days === 1 ? "" : "s"}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}
