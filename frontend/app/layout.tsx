import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "ATLAS-Σ Command Center",
  description: "Synthetic multi-rail financial infrastructure digital twin: settlement, liquidity, stress and adaptive control.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <aside className="side">
            <div className="brand">
              <div className="sig">Σ</div>
              <div>
                <b>ATLAS-Σ</b>
                <small>Settlement digital twin</small>
              </div>
            </div>
            <Nav />
            <div className="foot">
              Research simulator. All institutions, payments and balances are synthetic. Rail models are archetypes and do not connect to or
              replicate Fedwire, CHIPS, FedNow or RTP.
            </div>
          </aside>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
