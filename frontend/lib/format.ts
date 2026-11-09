// Display formatting only. Authoritative amounts stay integer minor units on the backend.

export const usd = (minor: number | null | undefined, digits = 1): string => {
  if (minor === null || minor === undefined || Number.isNaN(minor)) return "—";
  const v = minor / 100;
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(digits)}T`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(digits)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(digits)}M`;
  if (a >= 1e3) return `$${(v / 1e3).toFixed(digits)}K`;
  return `$${v.toFixed(2)}`;
};

export const pct = (x: number | null | undefined, digits = 2): string =>
  x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`;

export const mins = (s: number | null | undefined): string => (s === null || s === undefined ? "—" : `${(s / 60).toFixed(1)}m`);

export const num = (x: number | null | undefined, digits = 0): string =>
  x === null || x === undefined ? "—" : x.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });

export const hhmm = (iso: string): string => {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" });
};

export const short = (h: string, n = 10) => (h ? `${h.slice(0, n)}…` : "—");

export const RAIL_LABEL: Record<string, string> = {
  rtgs: "RTGS · gross",
  lsm: "LSM · netting",
  fednow: "Instant · public",
  rtp: "Instant · private",
};

export const RAIL_COLOR: Record<string, string> = {
  rtgs: "var(--c1)",
  lsm: "var(--c2)",
  fednow: "var(--c3)",
  rtp: "var(--c4)",
};
