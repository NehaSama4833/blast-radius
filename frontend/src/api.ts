import type { Ev, GraphData } from "./types";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: r.statusText }))).detail ?? r.statusText);
  return r.json();
}
const post = (u: string, b: unknown) => fetch(u, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });

export const getWorlds = () => fetch("/api/worlds").then(j<{ worlds: { name: string; services: number }[]; actions: string[]; change_kinds: string[] }>);
export const newSandbox = (world: string) => post("/api/sandbox", { world }).then(j<{ sandbox: string; world: string }>);
export const getGraph = (s: string) => fetch(`/api/graph/${s}`).then(j<GraphData>);
export const chaos = (sandbox: string, o: { service?: string; change_kind?: string; surprise?: boolean }) =>
  post("/api/chaos", { sandbox, ...o }).then(j<{ alerting: string[]; n_alerts: number }>);
export const resolve = (sandbox: string, investigation: string, action: string, ttr_min: number) =>
  post("/api/resolve", { sandbox, investigation, action, ttr_min }).then(j<Record<string, unknown>>);
export const postToDiscord = (sandbox: string, investigation: string) => post("/api/post", { sandbox, investigation }).then(j<Record<string, unknown>>);

/** Reads the server-sent-event stream from POST /api/investigate. */
export async function investigate(sandbox: string, onEvent: (e: Ev) => void) {
  const r = await post("/api/investigate", { sandbox });
  if (!r.ok || !r.body) throw new Error((await r.json().catch(() => ({ detail: "failed" }))).detail);
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      if (chunk.startsWith("data: ")) onEvent(JSON.parse(chunk.slice(6)));
    }
  }
}
