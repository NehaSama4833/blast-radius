import type { Ev, GraphData } from "./types";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: r.statusText }))).detail ?? r.statusText);
  return r.json();
}
const post = (u: string, b: unknown) => fetch(u, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });

export const getWorlds = () => fetch("/api/worlds").then(j<{ worlds: { name: string; services: number }[]; actions: string[]; change_kinds: string[] }>);
export const newSandbox = (world: string) => post("/api/sandbox", { world }).then(j<{ sandbox: string; world: string }>);
export const getGraph = (s: string) => fetch(`/api/graph/${s}`).then(j<GraphData>);
export const chaos = (sandbox: string, o: { service?: string; change_kind?: string; surprise?: boolean; again?: boolean }) =>
  post("/api/chaos", { sandbox, ...o }).then(j<{ alerting: string[]; n_alerts: number }>);
export const resolve = (sandbox: string, investigation: string, action: string, ttr_min: number) =>
  post("/api/resolve", { sandbox, investigation, action, ttr_min }).then(j<Record<string, unknown>>);
export const postToDiscord = (sandbox: string, investigation: string) => post("/api/post", { sandbox, investigation }).then(j<Record<string, unknown>>);

export type WhatIfData = { service: string; failing_now: string[]; at_risk: string[]; features: string[]; customers: number; arr: number };
export const whatIf = (sandbox: string, service: string) => post("/api/whatif", { sandbox, service }).then(j<WhatIfData>);
export type AskData = { answer: string; cites: string[]; rejected: number; faithfulness?: { names: number; numbers: number; flagged: string[] }; calls: { tool: string; params: Record<string, unknown> }[]; services: string[] };
export const askGraph = (sandbox: string, question: string) => post("/api/ask", { sandbox, question }).then(j<AskData>);
export type ImportData = { sandbox: string; world: string; services: number; edges: number; notes: string[] };
export const importCompose = (compose: string) => post("/api/import", { compose }).then(j<ImportData>);
export const investigate = (sandbox: string, onEvent: (e: Ev) => void) => stream("/api/investigate", sandbox, onEvent);
export const lateAlert = (sandbox: string, onEvent: (e: Ev) => void) => stream("/api/late", sandbox, onEvent);

/** Reads a server-sent-event stream from a POST endpoint. */
async function stream(url: string, sandbox: string, onEvent: (e: Ev) => void) {
  const r = await post(url, { sandbox });
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
