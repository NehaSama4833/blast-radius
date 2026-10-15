import { useState } from "react";
import { importCompose } from "./api";
import type { ImportData } from "./api";

const SAMPLE = `services:
  web:
    image: nginx
    ports: ["80:80"]
    depends_on: [api]
    healthcheck: {test: ["CMD", "true"]}
  api:
    build: ./api
    depends_on: [db, cache, events]
    healthcheck: {test: ["CMD", "true"]}
  worker:
    build: ./worker
    depends_on: [events, db]
    healthcheck: {test: ["CMD", "true"]}
  db:
    image: postgres:16        # no healthcheck: nobody gets paged when it breaks
  cache:
    image: redis:7
    healthcheck: {test: ["CMD", "true"]}
  events:
    image: redpanda
    healthcheck: {test: ["CMD", "true"]}
`;

export default function Import({ onDone, onClose }: { onDone: (d: ImportData) => void; onClose: () => void }) {
  const [text, setText] = useState(SAMPLE);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const go = async () => {
    setBusy(true); setErr("");
    try { onDone(await importCompose(text)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="modal" role="dialog" aria-label="Bring your own system">
      <div className="modal-box">
        <h3>Bring your own system</h3>
        <p className="hint">Paste a <code>docker-compose.yml</code>. Services become graph nodes, <code>depends_on</code> becomes edges, and anything without a healthcheck is treated as unmonitored. Then break it and let the agents investigate your architecture.</p>
        <textarea aria-label="docker-compose.yml" value={text} onChange={e => setText(e.target.value)} spellCheck={false} maxLength={20000} />
        {err && <div className="err">{err}</div>}
        <div className="btns"><button className="go" onClick={go} disabled={busy}>{busy ? "Building graph…" : "Build my graph"}</button><button onClick={onClose}>Cancel</button></div>
      </div>
    </div>
  );
}
