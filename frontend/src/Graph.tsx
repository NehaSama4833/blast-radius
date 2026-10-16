import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";
// @ts-ignore no types shipped
import dagre from "cytoscape-dagre";
import type { GraphData } from "./types";

cytoscape.use(dagre);

type Props = { data: GraphData | null; alerting: string[]; focus: string | null; cleared: string[]; onPick: (s: string) => void;
  reads?: Record<string, string>; proof?: string[] };

/** Services that (transitively, over sync edges) depend on `svc`: the nodes a failure of svc would take down. */
export function downstream(data: GraphData, svc: string): { nodes: Set<string>; edges: Set<string> } {
  const nodes = new Set([svc]), edges = new Set<string>();
  const q = [svc];
  while (q.length) {
    const cur = q.shift()!;
    for (const e of data.edges) if (e.target === cur && e.kind === "sync") {
      edges.add(`${e.source}>${e.target}`);
      if (!nodes.has(e.source)) { nodes.add(e.source); q.push(e.source); }
    }
  }
  return { nodes, edges };
}

export default function Graph({ data, alerting, focus, cleared, onPick, reads = {}, proof = [] }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<cytoscape.Core | null>(null);
  const pick = useRef(onPick); pick.current = onPick;

  useEffect(() => {
    if (!box.current || !data) return;
    cy.current?.destroy();
    const c = cytoscape({
      container: box.current,
      elements: [
        ...data.nodes.map(n => ({ data: { id: n.id, label: n.id, monitored: n.monitored ? 1 : 0 } })),
        ...data.edges.map(e => ({ data: { id: `${e.source}>${e.target}`, source: e.source, target: e.target, kind: e.kind } })),
      ],
      layout: { name: "dagre", rankDir: "TB", nodeSep: 18, rankSep: 55 } as any,
      style: [
        { selector: "node", style: { label: "data(label)", "font-size": 9, color: "#c9d1d9", "text-valign": "bottom", "text-margin-y": 3,
            "background-color": "#30363d", width: 16, height: 16, "border-width": 1, "border-color": "#6e7681" } },
        { selector: "node[monitored = 0]", style: { "border-style": "dashed", "background-color": "#161b22", "border-color": "#8b949e" } },
        { selector: "edge", style: { width: 1, "line-color": "#30363d", "target-arrow-color": "#30363d", "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.6 } },
        { selector: "edge[kind = 'async']", style: { "line-style": "dashed" } },
        { selector: ".alert", style: { "background-color": "#f85149", "border-color": "#ffa198", width: 20, height: 20 } },
        { selector: ".cleared", style: { "background-color": "#3fb950", "border-color": "#7ee787" } },
        { selector: ".path", style: { "line-color": "#d29922", "target-arrow-color": "#d29922", width: 2.5 } },
        { selector: "node.focus", style: { "border-color": "#d29922", "border-width": 4, "background-color": "#d29922", width: 24, height: 24 } },
        { selector: "node.onpath", style: { "border-color": "#d29922", "border-width": 2 } },
        { selector: ".dim", style: { opacity: 0.25 } },
        { selector: "node.read", style: { "border-width": 4, "transition-property": "border-color border-width", "transition-duration": 300 } as any },
        { selector: "node.proof", style: { "border-color": "#ffffff", "border-width": 5, "underlay-color": "#ffffff", "underlay-opacity": 0.25, "underlay-padding": 6 } as any },
      ],
      wheelSensitivity: 0.3,
      maxZoom: 1.6,
    });
    c.on("tap", "node", ev => pick.current(ev.target.id()));
    cy.current = c;
    const ro = new ResizeObserver(() => { c.resize(); c.fit(undefined, 20); });
    ro.observe(box.current);
    return () => { ro.disconnect(); c.destroy(); cy.current = null; };
  }, [data]);

  useEffect(() => {
    const c = cy.current; if (!c || !data) return;
    c.batch(() => {
      c.elements().removeClass("alert cleared path focus onpath dim read proof");
      c.nodes().removeStyle("border-color");
      const clr = new Set(cleared);
      alerting.forEach(a => c.getElementById(a).addClass(clr.has(a) ? "cleared" : "alert"));
      if (focus && c.getElementById(focus).nonempty()) {
        const d = downstream(data, focus);
        c.elements().addClass("dim");
        d.nodes.forEach(n => c.getElementById(n).removeClass("dim").addClass("onpath"));
        d.edges.forEach(e => c.getElementById(e).removeClass("dim").addClass("path"));
        c.getElementById(focus).addClass("focus");
      }
      Object.entries(reads).forEach(([n, color]) => {
        const el = c.getElementById(n);
        if (el.nonempty() && !el.hasClass("focus")) el.addClass("read").style("border-color", color);
      });
      if (proof.length) {
        c.elements().addClass("dim");
        proof.forEach(n => c.getElementById(n).removeClass("dim").addClass("proof"));
      }
    });
  }, [data, alerting, focus, cleared, reads, proof]);

  return <div ref={box} className="graph" />;
}
