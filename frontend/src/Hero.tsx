import { useEffect, useState } from "react";
import type { Ev, Result } from "./types";

export default function Hero({ events, result, running, nAlerts }: { events: Ev[]; result: Result | null; running: boolean; nAlerts: number }) {
  const [t0, setT0] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { if (running && events.length === 1) setT0(Date.now()); }, [running, events.length]);
  useEffect(() => { if (!running) return; const id = setInterval(() => setNow(Date.now()), 100); return () => clearInterval(id); }, [running]);
  if (!events.length) return null;
  const secs = result ? result.duration_s : t0 ? (now - t0) / 1000 : 0;
  const reads = events.filter(e => e.type === "read").length;
  const v = result?.verification;
  return (
    <div className="hero">
      <div><b>{nAlerts}</b><span>alerts</span></div>
      <div><b>{reads}</b><span>graph queries</span></div>
      <div><b>{secs.toFixed(1)}s</b><span>{result ? "to a verdict" : "elapsed"}</span></div>
      <div><b>{result ? `${result.claims.verified}/${result.claims.verified + result.claims.rejected}` : "…"}</b><span>claims proven</span></div>
      <div><b>{v ? `${v.cleared.length}/${v.cleared.length + v.remaining.length}` : "…"}</b><span>alerts cleared by the simulated fix</span></div>
      {result?.impact && <div><b>${(result.impact.arr / 1e6).toFixed(1)}M</b><span>ARR at risk</span></div>}
    </div>
  );
}
