import { useState } from "react";
import type { BoardRow, Finding, Hyp } from "./types";
import { COLOR } from "./agents";

function Receipt({ f }: { f: Finding }) {
  if (!f.receipt) return null;
  return (
    <div className="receipt">
      <div className="r-h">Receipt · graph version <code>{f.receipt.graph_version}</code></div>
      {f.receipt.calls.map((c, i) => <div key={i}><code>{c.tool}({Object.entries(c.params).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})</code></div>)}
      <div className="r-nodes">nodes read: {f.receipt.nodes_read.map(n => <code key={n}>{n}</code>)}</div>
    </div>
  );
}

export default function Board({ hyps, board, focus, onFocus, onProof }: {
  hyps: Hyp[]; board: BoardRow[] | null; focus: string | null; onFocus: (s: string) => void; onProof: (nodes: string[]) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const rows = board ?? hyps.map((h, i) => ({ hypothesis_id: h.id, rank: i + 1, service: h.service, structural_score: h.score, findings: [] as Finding[] }));
  if (!rows.length) return null;
  return (
    <div className="board">
      <h3>Hypothesis board <span className="sub">every finding is checked against the graph · click one for its receipt</span></h3>
      {rows.map(r => (
        <div key={r.hypothesis_id} className={`hyp ${focus === r.service ? "sel" : ""}`}>
          <div className="hyp-h" onClick={() => onFocus(r.service)} title="Show what this would take down">
            <b>#{r.rank} {r.service}</b>
            <span className="fit"><span className="bar" style={{ width: `${Math.round(r.structural_score * 100)}%` }} />{Math.round(r.structural_score * 100)}% fit</span>
          </div>
          {r.findings.map(f => (
            <div key={f.id} className={`finding ${f.effect}`} onClick={() => {
              setOpen(open === f.id ? null : f.id);
              onProof((f.receipt?.nodes_read ?? []).filter(n => n.startsWith("Service:")).map(n => n.slice(8)));
            }}>
              <span className="who" style={{ color: COLOR[f.agent] }}>{f.agent}</span> <span className="eff">{f.effect === "supports" ? "✓" : "✗"}</span> {f.text}
              {open === f.id && <Receipt f={f} />}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
