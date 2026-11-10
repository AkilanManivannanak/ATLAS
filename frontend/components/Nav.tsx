"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ITEMS = [
  ["/", "Global Network"],
  ["/rails", "Payment Infrastructure"],
  ["/treasury", "Treasury Center"],
  ["/stress", "Stress & Agent Lab"],
  ["/optimization", "Settlement Optimization"],
  ["/control", "Adaptive Control"],
  ["/decision", "Decision Center"],
  ["/research", "Research Studio"],
  ["/audit", "Audit & Governance"],
] as const;

export function Nav() {
  const path = usePathname();
  return (
    <nav className="nav">
      {ITEMS.map(([href, label], i) => (
        <Link key={href} href={href} className={path === href ? "active" : ""}>
          <span className="idx">{String(i + 1).padStart(2, "0")}</span>
          {label}
        </Link>
      ))}
    </nav>
  );
}
