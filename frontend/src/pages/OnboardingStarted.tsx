import { Link, useLocation, useSearchParams } from "react-router-dom";
import "../styles.css";
import "../started.css";

export default function OnboardingStarted() {
  const [params] = useSearchParams();
  const location = useLocation();
  const state = location.state as { name?: string } | null;
  const fleetId = params.get("fleet_id") ?? "";
  const clientId = params.get("client_id") ?? "";
  const workspaceUrl = `/conversations?fleet_id=${encodeURIComponent(fleetId)}&client_id=${encodeURIComponent(clientId)}`;

  return <main className="started-shell">
    <header className="started-nav"><Link className="brand dark" to="/">aucter<span>.</span></Link><span>Onboarding complete</span></header>
    <section className="started-card">
      <div className="started-mark">✓</div>
      <p className="section-no">YOUR BRAND IS IN MOTION</p>
      <h1>{state?.name ? `We’re getting to know you, ${state.name}.` : "We’re getting to know you."}</h1>
      <p className="started-lede">Your brief is safely stored and the research pipeline is ready. We’ll trace every claim to a source and ask before anything is published.</p>
      <div className="started-timeline">
        <div className="current"><i>1</i><span><strong>Researching your public work</strong><small>LinkedIn, GitHub, website and the sources you provided</small></span></div>
        <div><i>2</i><span><strong>Building your positioning</strong><small>Audience, proof points and a durable brand direction</small></span></div>
        <div><i>3</i><span><strong>Writing in your voice</strong><small>Site copy and content candidates, all held for review</small></span></div>
      </div>
      <div className="started-reference"><span>CLIENT REFERENCE</span><code>{clientId || "Pending"}</code><span>FLEET REFERENCE</span><code>{fleetId || "Pending"}</code></div>
      <div className="started-actions"><Link className="next" to={workspaceUrl}>Open your workspace →</Link><Link className="back" to="/onboarding">Edit the brief</Link></div>
    </section>
    <p className="started-footnote">Nothing will go live without your explicit approval.</p>
  </main>;
}
