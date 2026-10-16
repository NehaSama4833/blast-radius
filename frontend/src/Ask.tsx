import { useState } from "react";
import { askGraph } from "./api";
import type { AskData } from "./api";


export default function Ask({ sandbox, onProof, disabled, nodes }: { sandbox: string; onProof: (s: string[]) => void; disabled: boolean; nodes: { id: string; monitored: boolean }[] }) {
  const quiet = nodes.find(n => !n.monitored)?.id ?? nodes[0]?.id ?? "the database";
  const busiest = nodes[0]?.id ?? "the gateway";
  const EXAMPLES = [`Who should I page about ${quiet} right now?`, `What breaks if ${quiet} goes down?`, `What depends on ${busiest}?`];
  const [q, setQ] = useState("");
  const [a, setA] = useState<AskData | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const go = async (question: string) => {
    if (question.trim().length < 3) return;
    setBusy(true); setErr(""); setA(null);
    try { const r = await askGraph(sandbox, question); setA(r); onProof(r.services); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="ask">
      <form onSubmit={e => { e.preventDefault(); go(q); }}>
        <input aria-label="Ask the graph" maxLength={300} placeholder="Ask the graph anything… e.g. who owns ledger-db and is awake?" value={q}
               onChange={e => setQ(e.target.value)} disabled={disabled || busy} />
        <button disabled={disabled || busy || q.trim().length < 3}>{busy ? "Asking…" : "Ask"}</button>
      </form>
      {!a && !busy && !err && <div className="examples">{EXAMPLES.map(x => <span key={x} onClick={() => { setQ(x); go(x); }}>{x}</span>)}</div>}
      {err && <div className="note">{err}</div>}
      {a && (
        <div className="answer">
          <p>{a.answer}</p>
          <div className="receipt">
            <div className="r-h">Receipt · {a.calls.length} read-only graph quer{a.calls.length === 1 ? "y" : "ies"} · {a.cites.length} citation{a.cites.length === 1 ? "" : "s"} checked{a.rejected ? ` · ${a.rejected} invented citation(s) dropped` : ""}</div>
            {a.calls.map((c, i) => <div key={i}><code>{c.tool}({Object.entries(c.params).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})</code></div>)}
            <div className="r-nodes">{a.cites.map(c => <code key={c}>{c}</code>)}</div>
            {a.faithfulness && (a.faithfulness.flagged.length
              ? <div className="faith bad">⚠ {a.faithfulness.flagged.join("; ")}</div>
              : <div className="faith ok">✓ Fact-checked: {a.faithfulness.names} names and {a.faithfulness.numbers} numbers all appear in the tool results.</div>)}
          </div>
        </div>
      )}
    </div>
  );
}
