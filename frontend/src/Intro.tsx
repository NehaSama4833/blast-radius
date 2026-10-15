export default function Intro({ onSurprise, disabled, nServices }: { onSurprise: () => void; disabled: boolean; nServices: number }) {
  return (
    <div className="intro">
      <div className="kicker">GRAPH HACKS · FALKORDB</div>
      <h2>Six alerts at 3 AM.<br /><span>None of them is the problem.</span></h2>
      <p>A team of AI agents walks a live dependency graph of {nServices || "~30"} services to find the quiet thing that broke, proves every claim with a graph receipt, and tests the fix on a copy of the graph before a human approves it.</p>
      <button className="cta" disabled={disabled} onClick={onSurprise}>Break something at random</button>
      <div className="steps"><span>1 · Break it</span><span>2 · Investigate</span><span>3 · Check the receipts</span></div>
      <p className="fine">The culprit is hidden from you and from the agents. Your own private copy of the company graph.</p>
    </div>
  );
}
