import { useState } from "react";
import { postToDiscord, resolve } from "./api";
import type { Result } from "./types";

export default function Verdict({ r, sandbox, onFocus }: { r: Result; sandbox: string; onFocus: (s: string) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const a = r.actions[0];
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try { await fn(); setNote(ok); } catch (e) { setNote(String((e as Error).message)); } finally { setBusy(false); }
  };
  const undetermined = !r.root_cause;
  return (
    <div className={`verdict conf-${undetermined ? "none" : r.confidence}`}>
      <div className="v-h">
        <h3>{undetermined ? "Undetermined" : <>Root cause: <a onClick={() => onFocus(r.root_cause!)}>{r.root_cause}</a></>}</h3>
        <span className="badge">{undetermined ? "no confident answer" : `${r.confidence} confidence`}</span>
      </div>
      {!undetermined && !r.alerting.includes(r.root_cause!) && (
        <div className="silent">The culprit never raised an alert of its own. None of the {r.alerting.length} alerting services was the cause.</div>
      )}
      <ul>{r.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>
      {r.verification && <p className="sim">Simulation: {r.verification.summary}</p>}
      {r.impact && <p className="impact">At stake: {r.impact.features.join(", ")} · {r.impact.customers} customers · ${r.impact.arr.toLocaleString()} ARR</p>}
      {r.people && <p className="impact">Page: {r.people.pick.map(p => `${p.name} (${p.awake ? "awake" : "asleep"}, ${p.local_time})`).join(", ")} in {r.people.channel}</p>}
      <p className="meta">{r.claims.verified} claims checked against the graph, {r.claims.rejected} rejected · {r.duration_s}s</p>
      <div className="btns">
        <button disabled={busy || undetermined} onClick={() => act(() => postToDiscord(sandbox, r.investigation), "Posted the drafted message to the channel.")}>Approve &amp; post</button>
        <button disabled={busy || !a} onClick={() => act(() => resolve(sandbox, r.investigation, a.action, 10), "Saved to memory: next time this pattern is recognised.")}>Mark resolved</button>
      </div>
      {note && <p className="note">{note}</p>}
      <details><summary>Drafted message</summary><pre>{r.message}</pre></details>
    </div>
  );
}
