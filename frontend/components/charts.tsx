"use client";

import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";

export type Series = { key: string; label: string; color: string; values: { x: Date; y: number }[]; dashed?: boolean };

function useWidth(initial = 600) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const cw = Math.floor(el.getBoundingClientRect().width);
      if (cw > 0) setW(cw);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, w };
}

export function LineChart({ series, height = 220, yFormat = (v: number) => d3.format("~s")(v), area = false }: {
  series: Series[];
  height?: number;
  yFormat?: (v: number) => string;
  area?: boolean;
}) {
  const { ref, w } = useWidth();
  const [hover, setHover] = useState<{ i: number; px: number } | null>(null);
  const m = { t: 8, r: 12, b: 22, l: 58 };
  const all = series.flatMap((s) => s.values).filter((d) => Number.isFinite(d.y));
  const x = useMemo(() => d3.scaleTime().domain(d3.extent(all, (d) => d.x) as [Date, Date]).range([m.l, w - m.r]), [all, w]);
  const yMax = d3.max(all, (d) => d.y) ?? 1;
  const yMin = Math.min(0, d3.min(all, (d) => d.y) ?? 0);
  const y = d3.scaleLinear().domain([yMin, yMax || 1]).nice().range([height - m.b, m.t]);
  const line = d3.line<{ x: Date; y: number }>().x((d) => x(d.x)).y((d) => y(d.y));
  const areaGen = d3.area<{ x: Date; y: number }>().x((d) => x(d.x)).y0(y(0)).y1((d) => y(d.y));
  const xs = series[0]?.values.map((v) => v.x) ?? [];
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!xs.length) return;
    const px = e.nativeEvent.offsetX;
    const t = x.invert(px);
    const i = Math.max(0, Math.min(xs.length - 1, d3.bisector((d: Date) => d).center(xs, t)));
    setHover({ i, px: x(xs[i]) });
  };
  if (all.length < 2) return <div ref={ref} style={{ width: "100%" }}><div className="skeleton">no data for this series yet</div></div>;
  return (
    <div ref={ref} style={{ position: "relative", width: "100%", overflow: "hidden" }}>
      <svg width={w} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {y.ticks(4).map((t) => (
          <g key={t}>
            <line x1={m.l} x2={w - m.r} y1={y(t)} y2={y(t)} stroke="var(--line)" />
            <text x={m.l - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize={10} fill="var(--dim)">
              {yFormat(t)}
            </text>
          </g>
        ))}
        {x.ticks(6).map((t) => (
          <text key={+t} x={x(t)} y={height - 6} textAnchor="middle" fontSize={10} fill="var(--dim)">
            {d3.timeFormat("%H:%M")(t)}
          </text>
        ))}
        {series.map((s) => (
          <g key={s.key}>
            {area && <path d={areaGen(s.values) ?? ""} fill={s.color} opacity={0.08} />}
            <path d={line(s.values) ?? ""} fill="none" stroke={s.color} strokeWidth={1.6} strokeDasharray={s.dashed ? "4 3" : undefined} />
          </g>
        ))}
        {hover && <line x1={hover.px} x2={hover.px} y1={m.t} y2={height - m.b} stroke="var(--line-2)" />}
      </svg>
      {hover && (
        <div className="tooltip" style={{ left: Math.min(hover.px + 12, w - 220), top: 6 }}>
          <div className="dim">{d3.timeFormat("%H:%M")(xs[hover.i])} ET (sim)</div>
          {series.map((s) => (
            <div key={s.key}>
              <span style={{ color: s.color }}>■</span> {s.label}: {yFormat(s.values[hover.i]?.y ?? 0)}
            </div>
          ))}
        </div>
      )}
      <div className="legend">
        {series.map((s) => (
          <span key={s.key}>
            <i style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export type BarRow = { label: string; value: number; lo?: number; hi?: number; color?: string; highlight?: boolean; note?: string };

export function HBarChart({ rows, format, height, zeroLine = true }: { rows: BarRow[]; format: (v: number) => string; height?: number; zeroLine?: boolean }) {
  const { ref, w } = useWidth();
  const rowH = 26;
  const h = height ?? rows.length * rowH + 24;
  const m = { l: Math.min(150, w * 0.32), r: 78, t: 4, b: 18 };
  if (!rows.length) return <div ref={ref} style={{ width: "100%" }}><div className="skeleton">no data</div></div>;
  const vals = rows.flatMap((r) => [r.value, r.lo ?? r.value, r.hi ?? r.value, 0]).filter(Number.isFinite);
  const [lo0, hi0] = d3.extent(vals) as [number, number];
  const x = d3.scaleLinear().domain(lo0 === hi0 ? [lo0 - 1, hi0 + 1] : [lo0, hi0]).nice().range([m.l, w - m.r]);
  return (
    <div ref={ref} style={{ width: "100%", overflow: "hidden" }}>
      <svg width={w} height={h}>
        {x.ticks(5).map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={m.t} y2={h - m.b} stroke="var(--line)" />
            <text x={x(t)} y={h - 4} textAnchor="middle" fontSize={10} fill="var(--dim)">
              {format(t)}
            </text>
          </g>
        ))}
        {zeroLine && <line x1={x(0)} x2={x(0)} y1={m.t} y2={h - m.b} stroke="var(--muted)" />}
        {rows.map((r, i) => {
          const yy = m.t + i * rowH + 4;
          const x0 = x(Math.min(0, r.value));
          const x1 = x(Math.max(0, r.value));
          return (
            <g key={r.label}>
              <text x={m.l - 10} y={yy + 9} textAnchor="end" fontSize={11} fill={r.highlight ? "var(--text)" : "var(--muted)"}>
                {r.label}
              </text>
              <rect x={x0} y={yy} width={Math.max(1, x1 - x0)} height={16} fill={r.color ?? "var(--accent)"} opacity={r.highlight ? 0.95 : 0.6} />
              {r.lo !== undefined && r.hi !== undefined && (
                <g stroke="var(--text)" strokeWidth={1}>
                  <line x1={x(r.lo)} x2={x(r.hi)} y1={yy + 8} y2={yy + 8} />
                  <line x1={x(r.lo)} x2={x(r.lo)} y1={yy + 3} y2={yy + 13} />
                  <line x1={x(r.hi)} x2={x(r.hi)} y1={yy + 3} y2={yy + 13} />
                </g>
              )}
              <text x={w - m.r + 8} y={yy + 9} fontSize={11} fill="var(--text)">
                {format(r.value)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function Sparkbar({ value, max, color = "var(--accent)" }: { value: number; max: number; color?: string }) {
  return (
    <div className="bar-track" style={{ width: 90 }}>
      <div className="bar-fill" style={{ width: `${Math.max(0, Math.min(1, value / (max || 1))) * 100}%`, background: color }} />
    </div>
  );
}
