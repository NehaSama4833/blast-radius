import type { Ev } from "./types";
const LANES = ["Lead", "Changes", "Impact", "History", "People"];
export default function Lanes({ events }: { events: Ev[] }) {
  return (
    <div className="lanes">
      {LANES.map(l => (
        <div className="lane" key={l}>
          <h4>{l}</h4>
          {events.filter(e => e.agent === l && e.type !== "done").map((e, i) => (
            <div key={i} className={`ev ev-${e.type}`}>{e.text}</div>
          ))}
        </div>
      ))}
    </div>
  );
}
