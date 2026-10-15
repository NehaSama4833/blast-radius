import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { chaos, getGraph, getWorlds, investigate, newSandbox } from "./api";
import Graph from "./Graph";
import Lanes from "./Lanes";
import Board from "./Board";
import Verdict from "./Verdict";
import Intro from "./Intro";
import Hero from "./Hero";
import { COLOR } from "./agents";
import type { Ev, GraphData, Hyp, Result } from "./types";

const PACE_MS = 140;   // events are replayed at a readable pace even when the backend answers in a fraction of a second

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
  const [proof, setProof] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const queue = useRef<Ev[]>([]);

  const reset = () => { queue.current = []; setEvents([]); setResult(null); setFocus(null); setProof([]); };

  const start = useCallback(async (w: string) => {
    setErr(""); queue.current = []; setEvents([]); setResult(null); setFocus(null); setProof([]); setAlerting([]); setLoading(true);
    try {
      const s = await newSandbox(w);
      setSbx(s.sandbox); setWorld(w);
      setGraph(await getGraph(s.sandbox));
    } catch (e) { setErr((e as Error).message); } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    getWorlds().then(w => { setWorlds(w.worlds.map(x => x.name)); setKinds(w.change_kinds); setKind(w.change_kinds[0]); start(w.worlds[0].name); })
      .catch(e => setErr(e.message));
  }, [start]);

  // drain the event queue at a human pace
  useEffect(() => {
    const id = setInterval(() => {
      const e = queue.current.shift();
      if (!e) return;
      setEvents(prev => [...prev, e]);
      if (e.type === "done" && e.result) { setResult(e.result); setFocus(e.result.root_cause); setRunning(false); }
      if (e.type === "error") setRunning(false);
    }, PACE_MS);
    return () => clearInterval(id);
  }, []);

  const hyps: Hyp[] = useMemo(() => events.find(e => e.type === "hypotheses")?.hypotheses ?? [], [events]);
  const cleared = useMemo(() => events.find(e => e.type === "verify")?.verification?.cleared ?? [], [events]);
  const reads = useMemo(() => {
    if (!running) return {};
    const m: Record<string, string> = {};
    events.slice(-12).forEach(e => { if (e.type === "read") (e.services ?? []).forEach(s => { m[s] = COLOR[e.agent] ?? "#fff"; }); });
    return m;
  }, [events, running]);

  const doChaos = async (o: { service?: string; change_kind?: string; surprise?: boolean }) => {
    setErr(""); setBusy(true); reset();
    try { setAlerting((await chaos(sbx, o)).alerting); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const doInvestigate = async () => {
    setErr(""); setBusy(true); reset(); setRunning(true);
    try { await investigate(sbx, e => { queue.current.push(e); }); }
    catch (e) { setErr((e as Error).message); setRunning(false); }
    finally { setBusy(false); }
  };

  const idle = !alerting.length && !events.length;
  return (
    <div className="app">
      <header>
        <h1><span className="logo">◉</span> Blast Radius</h1>
        <label>World
          <select aria-label="World" value={world} onChange={e => start(e.target.value)}>{worlds.map(w => <option key={w}>{w}</option>)}</select>
        </label>
        <div className="chaos">
          <select aria-label="Service to break" value={svc} onChange={e => setSvc(e.target.value)}>
            <option value="">break a service…</option>
            {graph?.nodes.map(n => <option key={n.id} value={n.id}>{n.id}{n.monitored ? "" : " (unmonitored)"}</option>)}
          </select>
          <select aria-label="Kind of change" value={kind} onChange={e => setKind(e.target.value)}>{kinds.map(k => <option key={k}>{k}</option>)}</select>
          <button disabled={!svc || busy || running} onClick={() => doChaos({ service: svc, change_kind: kind })}>Break it</button>
          <button disabled={busy || running || !sbx} onClick={() => doChaos({ surprise: true })}>Surprise me</button>
        </div>
        <button className={`go ${alerting.length && !events.length ? "glow" : ""}`} disabled={busy || running || !alerting.length} onClick={doInvestigate}>
          {running ? "Investigating…" : `Investigate ${alerting.length ? `${alerting.length} alerts` : ""}`}
        </button>
      </header>
      {err && <div className="err" role="alert">{err}</div>}
      {events.some(e => e.replay) && <div className="notice" role="status">Showing a recorded replay: the live investigation limit for today was reached.</div>}
      {loading && <div className="notice" role="status">Setting up your private copy of the company graph…</div>}
      <main>
        <section className="left">
          <Graph data={graph} alerting={alerting} focus={proof.length ? null : focus} cleared={cleared} onPick={s => { setProof([]); setFocus(s); }} reads={reads} proof={proof} />
          {alerting.length > 0 && !events.length && <div className="storm">{alerting.length} services are alerting. The real cause may not be one of them.</div>}
          <div className="legend"><i className="d red" /> alerting <i className="d green" /> cleared by simulated fix <i className="d amber" /> suspect + what it takes down <i className="d hollow" /> unmonitored · dashed edge = async · colored rings = agent reading that node</div>
        </section>
        <section className="right">
          {idle ? <Intro onSurprise={() => doChaos({ surprise: true })} disabled={busy || !sbx} nServices={graph?.nodes.length ?? 0} /> : null}
          {!idle && !events.length && <p className="hint">Press <b>Investigate</b>. Five agents will split the work and write their findings onto a shared board inside the graph.</p>}
          <Hero events={events} result={result} running={running} nAlerts={alerting.length} />
          {result && <Verdict r={result} sandbox={sbx} onFocus={s => { setProof([]); setFocus(s); }} />}
          {events.length > 0 && <Lanes events={events} running={running} />}
          <Board hyps={hyps} board={result?.board ?? null} focus={focus} onFocus={s => { setProof([]); setFocus(s); }} onProof={setProof} />
        </section>
      </main>
    </div>
  );
}
