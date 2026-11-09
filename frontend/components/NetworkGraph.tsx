"use client";

import * as d3 from "d3";
import { useEffect, useRef, useState } from "react";
import { NetworkEdge, NetworkNode } from "@/lib/api";
import { usd } from "@/lib/format";

type SimNode = NetworkNode & d3.SimulationNodeDatum;
type SimLink = d3.SimulationLinkDatum<SimNode> & { value_minor: number; count: number; rail: string };

export const NETWORK_MAX_LINKS = 70;

export function NetworkGraph({ nodes, edges, onSelect, selected, height = 520 }: {
  nodes: NetworkNode[];
  edges: NetworkEdge[];
  onSelect?: (id: string) => void;
  selected?: string | null;
  height?: number;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [tip, setTip] = useState<{ x: number; y: number; html: string } | null>(null);

  useEffect(() => {
    const el = wrap.current;
    const svg = svgRef.current;
    if (!el || !svg || !nodes.length) return;
    const w = el.clientWidth;
    const root = d3.select(svg).attr("width", w).attr("height", height);
    root.selectAll("*").remove();

    // collapse rails into one directed edge per pair for the overview
    const pair = new Map<string, SimLink>();
    for (const e of edges) {
      const k = `${e.source}->${e.target}`;
      const cur = pair.get(k);
      if (cur) {
        cur.value_minor += e.value_minor;
        cur.count += e.count;
      } else pair.set(k, { source: e.source, target: e.target, value_minor: e.value_minor, count: e.count, rail: e.rail });
    }
    const MAX_LINKS = 70;
    const links = [...pair.values()].sort((a, b) => b.value_minor - a.value_minor).slice(0, MAX_LINKS);
    const simNodes: SimNode[] = nodes.map((n) => ({ ...n }));
    const maxS = d3.max(simNodes, (n) => n.out_strength_minor + n.in_strength_minor) ?? 1;
    const r = d3.scaleSqrt().domain([0, maxS]).range([5, 26]);
    const maxV = d3.max(links, (l) => l.value_minor) ?? 1;
    const lw = d3.scaleLinear().domain([0, maxV]).range([0.3, 5]);
    const lo = d3.scaleLinear().domain([0, maxV]).range([0.08, 0.6]);

    const defs = root.append("defs");
    defs.append("marker").attr("id", "arr").attr("viewBox", "0 -4 8 8").attr("refX", 8).attr("refY", 0).attr("markerWidth", 5).attr("markerHeight", 5)
      .attr("orient", "auto").append("path").attr("d", "M0,-4L8,0L0,4").attr("fill", "#4f6a99");

    const g = root.append("g");
    root.call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.4, 4]).on("zoom", (ev) => g.attr("transform", ev.transform.toString())));

    const link = g.append("g").selectAll("path").data(links).join("path")
      .attr("fill", "none").attr("stroke", "#5b7db8").attr("stroke-width", (d) => lw(d.value_minor)).attr("stroke-opacity", (d) => lo(d.value_minor))
      .attr("marker-end", "url(#arr)");

    const node = g.append("g").selectAll<SVGGElement, SimNode>("g").data(simNodes).join("g").style("cursor", "pointer");
    node.append("circle")
      .attr("r", (d) => r(d.out_strength_minor + d.in_strength_minor))
      .attr("fill", (d) => (d.tier === "core" ? "rgba(110,168,255,0.22)" : "rgba(127,143,171,0.14)"))
      .attr("stroke", (d) => (d.id === selected ? "#f2b341" : d.tier === "core" ? "#6ea8ff" : "#7f8fab"))
      .attr("stroke-width", (d) => (d.id === selected ? 2.4 : 1.2));
    node.append("circle").attr("r", (d) => Math.max(1.5, 10 * d.systemic_score ** 2)).attr("fill", (d) => (d.systemic_score > 0.8 ? "#f2b341" : "#6ea8ff"));
    node.append("text").text((d) => d.id.replace("bank-", "")).attr("dy", (d) => r(d.out_strength_minor + d.in_strength_minor) + 11)
      .attr("text-anchor", "middle").attr("font-size", 9.5).attr("fill", "#7f8fab");

    node.on("click", (_, d) => onSelect?.(d.id))
      .on("mousemove", (ev, d) => {
        const [mx, my] = d3.pointer(ev, el);
        setTip({ x: mx, y: my, html: `${d.id} · ${d.tier}\nout ${usd(d.out_strength_minor)} · in ${usd(d.in_strength_minor)}\nPageRank ${d.pagerank.toFixed(3)} · betweenness ${d.betweenness.toFixed(3)}\nsystemic score ${d.systemic_score.toFixed(2)}` });
      })
      .on("mouseleave", () => setTip(null));

    const sim = d3.forceSimulation<SimNode>(simNodes)
      .force("link", d3.forceLink<SimNode, SimLink>(links).id((d) => d.id).distance(140).strength(0.02))
      .force("charge", d3.forceManyBody().strength(-420))
      .force("radial", d3.forceRadial<SimNode>((d) => (d.tier === "core" ? Math.min(w, height) * 0.13 : Math.min(w, height) * 0.38), w / 2, height / 2).strength(0.9))
      .force("collide", d3.forceCollide<SimNode>().radius((d) => r(d.out_strength_minor + d.in_strength_minor) + 8))
      .on("tick", () => {
        link.attr("d", (d) => {
          const s = d.source as SimNode, t = d.target as SimNode;
          const dx = (t.x ?? 0) - (s.x ?? 0), dy = (t.y ?? 0) - (s.y ?? 0);
          const dist = Math.hypot(dx, dy) || 1;
          const rt = r(t.out_strength_minor + t.in_strength_minor) + 3;
          const tx = (t.x ?? 0) - (dx / dist) * rt, ty = (t.y ?? 0) - (dy / dist) * rt;
          return `M${s.x},${s.y}A${dist * 1.6},${dist * 1.6} 0 0,1 ${tx},${ty}`;
        });
        node.attr("transform", (d) => `translate(${d.x},${d.y})`);
      });
    node.call(d3.drag<SVGGElement, SimNode>()
      .on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
    return () => {
      sim.stop();
    };
  }, [nodes, edges, selected, height, onSelect]);

  return (
    <div ref={wrap} style={{ position: "relative", width: "100%" }}>
      <svg ref={svgRef} />
      {tip && (
        <div className="tooltip" style={{ left: tip.x + 14, top: tip.y + 10, whiteSpace: "pre" }}>
          {tip.html}
        </div>
      )}
    </div>
  );
}
