import { useCallback, useEffect, useMemo, useState } from "react";
import { chaos, getGraph, getWorlds, investigate, newSandbox } from "./api";
import Graph from "./Graph";
import Lanes from "./Lanes";
import Board from "./Board";
import Verdict from "./Verdict";
import type { Ev, GraphData, Hyp, Result } from "./types";

export default function App() {
  const [worlds, setWorlds] = useState<string[]>([]);
  const [kinds, setKinds] = useState<string[]>([]);
  const [world, setWorld] = useState("");
  const [sbx, setSbx] = useState("");
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [alerting, setAlerting] = useState<string[]>([]);
  const [svc, setSvc] = useState("");
  const [kind, setKind] = useState("");
  const [events, setEvents] = useState<Ev[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const start = useCallback(async (w: string) => {
    setErr(""); setEvents([]); setResult(null); setFocus(null); setAlerting([]);
    try {
      const s = await newSandbox(w);
      setSbx(s.sandbox); setWorld(w);
      setGraph(await getGraph(s.sandbox));
    } catch (e) { setErr((e as Error).message); }
  }, []);

  useEffect(() => {
    getWorlds().then(w => { setWorlds(w.worlds.map(x => x.name)); setKinds(w.change_kinds); setKind(w.change_kinds[0]); start(w.worlds[0].name); })
      .catch(e => setErr(e.message));
  }, [start]);

  const hyps: Hyp[] = useMemo(() => events.find(e => e.type === "hypotheses")?.hypotheses ?? [], [events]);
  const cleared = useMemo(() => events.find(e => e.type === "verify")?.verification?.cleared ?? [], [events]);

  const doChaos = async (o: { service?: string; change_kind?: string; surprise?: boolean }) => {
    setErr(""); setBusy(true); setEvents([]); setResult(null); setFocus(null);
    try { setAlerting((await chaos(sbx, o)).alerting); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const doInvestigate = async () => {
    setErr(""); setBusy(true); setEvents([]); setResult(null);
    try {
      await investigate(sbx, e => {
        setEvents(prev => [...prev, e]);
        if (e.type === "done" && e.result) { setResult(e.result); setFocus(e.result.root_cause); }
      });
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="app">
      <header>
        <h1>Blast Radius</h1>
        <label>World
          <select value={world} onChange={e => start(e.target.value)}>{worlds.map(w => <option key={w}>{w}</option>)}</select>
        </label>
        <div className="chaos">
          <select value={svc} onChange={e => setSvc(e.target.value)}>
            <option value="">break a service…</option>
            {graph?.nodes.map(n => <option key={n.id} value={n.id}>{n.id}{n.monitored ? "" : " (unmonitored)"}</option>)}
          </select>
          <select value={kind} onChange={e => setKind(e.target.value)}>{kinds.map(k => <option key={k}>{k}</option>)}</select>
          <button disabled={!svc || busy} onClick={() => doChaos({ service: svc, change_kind: kind })}>Break it</button>
          <button disabled={busy || !sbx} onClick={() => doChaos({ surprise: true })}>Surprise me</button>
        </div>
        <button className="go" disabled={busy || !alerting.length} onClick={doInvestigate}>Investigate {alerting.length ? `(${alerting.length} alerts)` : ""}</button>
      </header>
      {err && <div className="err">{err}</div>}
      <main>
        <section className="left">
          <Graph data={graph} alerting={alerting} focus={focus} cleared={cleared} onPick={setFocus} />
          <div className="legend"><i className="d red" /> alerting <i className="d green" /> cleared by simulated fix <i className="d amber" /> suspect + what it takes down <i className="d hollow" /> unmonitored · dashed edge = async</div>
        </section>
        <section className="right">
          {!events.length && <p className="hint">1. Break something (or press <b>Surprise me</b>). 2. Press <b>Investigate</b>. The culprit is never shown to you or the agents up front.</p>}
          <Lanes events={events} />
          <Board hyps={hyps} board={result?.board ?? null} focus={focus} onFocus={setFocus} />
          {result && <Verdict r={result} sandbox={sbx} onFocus={setFocus} />}
        </section>
      </main>
    </div>
  );
}
