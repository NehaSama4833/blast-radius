import type { BoardRow, Hyp } from "./types";
export default function Board({ hyps, board, focus, onFocus }: { hyps: Hyp[]; board: BoardRow[] | null; focus: string | null; onFocus: (s: string) => void }) {
  const rows = board ?? hyps.map((h, i) => ({ hypothesis_id: h.id, rank: i + 1, service: h.service, structural_score: h.score, findings: [] }));
  if (!rows.length) return null;
  return (
    <div className="board">
      <h3>Hypotheses</h3>
      {rows.map(r => (
        <div key={r.hypothesis_id} className={`hyp ${focus === r.service ? "sel" : ""}`} onClick={() => onFocus(r.service)} title="Click to show the dependency path on the map">
          <div className="hyp-h"><b>#{r.rank} {r.service}</b><span>{r.structural_score.toFixed(2)}</span></div>
          {r.findings.map(f => (
            <div key={f.id} className={`finding ${f.effect}`}><span className="who">{f.agent}</span> {f.text}</div>
          ))}
        </div>
      ))}
    </div>
  );
}
