import type { Ev } from "./types";
import { AGENTS, COLOR, ROLE } from "./agents";

export default function Lanes({ events, running }: { events: Ev[]; running: boolean }) {
  return (
    <div className="lanes">
      {AGENTS.map(a => {
        const mine = events.filter(e => e.agent === a && e.type !== "done");
        const last = mine[mine.length - 1];
        const working = running && !!mine.length && !events.some(e => e.type === "done");
        return (
          <div className="lane" key={a} style={{ borderTopColor: COLOR[a] }}>
            <h4 style={{ color: COLOR[a] }}>
              <span className={`dot ${working ? "pulse" : ""}`} style={{ background: COLOR[a] }} />{a}
            </h4>
            <div className="role">{ROLE[a]}</div>
            {mine.map((e, i) => e.type === "read"
              ? <div key={i} className="ev ev-read">→ {e.tool}{e.services?.length ? ` · ${e.services.length} node${e.services.length > 1 ? "s" : ""}` : ""}</div>
              : <div key={i} className={`ev ev-${e.type}`} title={e.text}>{e.text.length > 140 ? e.text.slice(0, 137) + "…" : e.text}</div>)}
            {!mine.length && <div className="ev idle">waiting</div>}
            {last && last.type === "finding" && <span className="sr-only">latest: {last.text}</span>}
          </div>
        );
      })}
    </div>
  );
}
