import { useEffect, useState } from "react";

function md(text: string) {
  // tiny, safe renderer: headings, bullets, bold, inline code, paragraphs (text is escaped by React)
  const out: JSX.Element[] = [];
  let list: string[] = [];
  const inline = (s: string, k: string) => s.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/).map((p, i) =>
    p.startsWith("**") ? <b key={k + i}>{p.slice(2, -2)}</b> : p.startsWith("`") ? <code key={k + i}>{p.slice(1, -1)}</code>
      : p.startsWith("*") && p.endsWith("*") && p.length > 2 ? <i key={k + i}>{p.slice(1, -1)}</i> : p);
  const flush = () => { if (list.length) { out.push(<ul key={"u" + out.length}>{list.map((l, i) => <li key={i}>{inline(l, "l" + i)}</li>)}</ul>); list = []; } };
  text.split("\n").forEach((line, i) => {
    if (line.startsWith("- ")) { list.push(line.slice(2)); return; }
    flush();
    if (line.startsWith("# ")) out.push(<h2 key={i}>{line.slice(2)}</h2>);
    else if (line.startsWith("## ")) out.push(<h4 key={i}>{line.slice(3)}</h4>);
    else if (line.trim()) out.push(<p key={i}>{inline(line, "p" + i)}</p>);
  });
  flush();
  return out;
}

export default function Postmortem({ sandbox, inv, onClose }: { sandbox: string; inv: string; onClose: () => void }) {
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    fetch(`/api/postmortem/${sandbox}/${inv}`).then(r => r.ok ? r.json() : r.json().then(j => Promise.reject(new Error(j.detail))))
      .then(j => setText(j.markdown)).catch(e => setErr(e.message));
  }, [sandbox, inv]);
  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    a.download = `postmortem-${inv}.md`; a.click();
  };
  return (
    <div className="modal" role="dialog" aria-label="Postmortem">
      <div className="modal-box pm">
        {err ? <div className="err">{err}</div> : text ? md(text) : <p className="hint">Writing it from the graph…</p>}
        <div className="btns">
          <button className="go" disabled={!text} onClick={download}>Download .md</button>
          <button disabled={!text} onClick={() => navigator.clipboard?.writeText(text)}>Copy</button>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
