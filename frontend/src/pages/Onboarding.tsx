import { FormEvent, useEffect, useState } from "react";
import "../styles.css";
import { fetchMe, getWorkspaceId } from "../auth/api";

const csv = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
const lines = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    fullName: "", email: "", role: "", company: "", linkedin: "", website: "", github: "",
    goal: "build_authority", audience: "", knownFor: "", topics: "", cta: "",
    proof: "", proofUrl: "", samples: "", tone: "", use: "", avoid: "",
    platforms: ["x"], cadence: 3, approval: "whatsapp", phone: "", offLimits: "",
    research: false, profile: false, publishApproval: true,
  });
  // This page is public (unauthenticated), but an operator navigating here is
  // usually already logged in — populate the workspace_id cache so submissions
  // land in their real workspace, not the pre-login "personal" placeholder.
  useEffect(() => { void fetchMe(); }, []);
  const set = (key: string, value: unknown) => setForm((current) => ({...current, [key]: value}));
  const payload = {
    workspace_id: getWorkspaceId(),
    identity: {full_name: form.fullName, email: form.email, job_title: form.role,
      company: form.company, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone},
    sources: {linkedin_url: form.linkedin, website_url: form.website, github_url: form.github},
    positioning: {primary_goal: form.goal, audience: csv(form.audience), known_for: form.knownFor,
      content_topics: csv(form.topics), call_to_action: form.cta},
    proof_points: form.proof ? [{claim: form.proof, source_url: form.proofUrl}] : [],
    voice: {writing_samples: lines(form.samples), tone_words: csv(form.tone),
      phrases_to_use: csv(form.use), phrases_to_avoid: csv(form.avoid)},
    publishing: {platforms: form.platforms, posts_per_week: form.cadence,
      approval_channel: form.approval, whatsapp_number: form.phone, topics_to_avoid: csv(form.offLimits)},
    consent: {research_public_sources: form.research, store_brand_profile: form.profile,
      require_approval_before_publish: form.publishApproval},
  };
  const errorText = (detail: unknown) => Array.isArray(detail)
    ? detail.map((item: {loc?: string[]; msg?: string}) => `${item.loc?.at(-1)?.replaceAll("_", " ")}: ${item.msg}`).join(" · ")
    : typeof detail === "string" ? detail : "Please check the information and try again.";
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/onboarding/submit", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
      const result = await response.json();
      if (!response.ok) throw new Error(errorText(result.detail));
      setMessage(`You’re in. Research has started. Reference: ${result.client_id}`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Submission failed"); }
    finally { setBusy(false); }
  }
  const names = ["You", "Direction", "Proof & voice", "Publishing", "Review"];
  return <main className="shell"><aside className="intro"><a className="brand" href="/">aucter<span>.</span></a><div className="intro-copy"><p className="eyebrow">Your personal brand, with receipts.</p><h1>Let’s understand what makes you worth following.</h1><p>Give us the raw material. We research, position and write—then ask before anything goes live.</p></div><div className="trust"><span>01</span><p><strong>Nothing publishes without you.</strong><br/>Every site and post waits for explicit approval.</p></div></aside>
  <section className="form-panel"><header className="progress-head"><div><span>Onboarding</span><strong>{step+1} of 5</strong></div><div className="bar"><i style={{width:`${(step+1)*20}%`}}/></div></header><nav className="steps">{names.map((name,index)=><button type="button" key={name} className={index===step?"active":index<step?"done":""} onClick={()=>index<step&&setStep(index)}><b>{index<step?"✓":index+1}</b>{name}</button>)}</nav>
  <form onSubmit={submit}><div className="page"><p className="section-no">THE BRIEF</p>
  {step===0&&<><h2>First, the basics.</h2><p className="hint">Public information we’ll use to understand your work.</p><div className="grid"><Field label="Full name"><input required value={form.fullName} onChange={e=>set("fullName",e.target.value)}/></Field><Field label="Work email"><input required type="email" value={form.email} onChange={e=>set("email",e.target.value)}/></Field><Field label="Current role"><input required value={form.role} onChange={e=>set("role",e.target.value)}/></Field><Field label="Company"><input value={form.company} onChange={e=>set("company",e.target.value)}/></Field></div><Field label="LinkedIn profile"><input required type="url" value={form.linkedin} onChange={e=>set("linkedin",e.target.value)}/></Field><div className="grid"><Field label="Website"><input type="url" value={form.website} onChange={e=>set("website",e.target.value)}/></Field><Field label="GitHub"><input type="url" value={form.github} onChange={e=>set("github",e.target.value)}/></Field></div></>}
  {step===1&&<><h2>Where should this take you?</h2><p className="hint">Direction helps us choose what to emphasize.</p><Field label="Primary goal"><select value={form.goal} onChange={e=>set("goal",e.target.value)}><option value="build_authority">Build authority</option><option value="attract_customers">Attract customers</option><option value="find_opportunities">Find opportunities</option><option value="launch_product">Launch a product</option><option value="other">Other</option></select></Field><Field label="Audience (comma separated)"><input required value={form.audience} onChange={e=>set("audience",e.target.value)}/></Field><Field label="What should people know you for?"><textarea required value={form.knownFor} onChange={e=>set("knownFor",e.target.value)}/></Field><Field label="Content topics"><input required value={form.topics} onChange={e=>set("topics",e.target.value)}/></Field><Field label="Call to action"><input value={form.cta} onChange={e=>set("cta",e.target.value)}/></Field></>}
  {step===2&&<><h2>Give us the receipts—and your voice.</h2><p className="hint">Evidence keeps it credible. Real samples keep it sounding like you.</p><Field label="Achievement or proof point"><textarea value={form.proof} onChange={e=>set("proof",e.target.value)}/></Field><Field label="Source URL"><input type="url" value={form.proofUrl} onChange={e=>set("proofUrl",e.target.value)}/></Field><Field label="Writing samples (one per line)"><textarea className="tall" value={form.samples} onChange={e=>set("samples",e.target.value)}/></Field><div className="grid"><Field label="Tone words"><input value={form.tone} onChange={e=>set("tone",e.target.value)}/></Field><Field label="Phrases you use"><input value={form.use} onChange={e=>set("use",e.target.value)}/></Field></div><Field label="Phrases to avoid"><input value={form.avoid} onChange={e=>set("avoid",e.target.value)}/></Field></>}
  {step===3&&<><h2>Set the publishing boundaries.</h2><p className="hint">Preferences, not permission. You approve every post.</p><Field label="Posts per week"><input type="number" min="1" max="21" value={form.cadence} onChange={e=>set("cadence",Math.min(21,Math.max(1,+e.target.value)))}/></Field><Field label="Approval method"><select value={form.approval} onChange={e=>set("approval",e.target.value)}><option value="whatsapp">WhatsApp</option><option value="web">Web dashboard</option></select></Field>{form.approval==="whatsapp"&&<Field label="WhatsApp number"><input required value={form.phone} onChange={e=>set("phone",e.target.value)}/></Field>}<Field label="Off-limit topics"><textarea value={form.offLimits} onChange={e=>set("offLimits",e.target.value)}/></Field></>}
  {step===4&&<><h2>One last check.</h2><p className="hint">We begin with public-source research, then show you what we found.</p><div className="review"><div><span>Identity</span><p>{form.fullName} · {form.role}</p></div><div><span>Audience</span><p>{form.audience}</p></div><div><span>Known for</span><p>{form.knownFor}</p></div><div><span>Cadence</span><p>{form.cadence} posts/week</p></div></div><div className="consents"><Check value={form.research} onChange={v=>set("research",v)}>Research the public sources I provided.</Check><Check value={form.profile} onChange={v=>set("profile",v)}>Store my private brand and voice profile.</Check><Check value={form.publishApproval} onChange={v=>set("publishApproval",v)}>Nothing publishes without my approval.</Check></div></>}
  </div>{message&&<div className={`message ${message.startsWith("You’re in")?"success":""}`}>{message}</div>}<footer className="actions"><a className="quiet" href="/">Exit</a><div>{step>0&&<button type="button" className="back" onClick={()=>setStep(step-1)}>Back</button>}{step<4?<button type="button" className="next" onClick={()=>setStep(step+1)}>Continue →</button>:<button className="next" disabled={busy}>{busy?"Starting…":"Start my brand →"}</button>}</div></footer></form></section></main>;
}

function Field({label,children}:{label:string;children:React.ReactNode}) { return <label className="field"><span>{label}</span>{children}</label>; }
function Check({value,onChange,children}:{value:boolean;onChange:(value:boolean)=>void;children:React.ReactNode}) { return <label className="check"><input type="checkbox" checked={value} onChange={e=>onChange(e.target.checked)}/><i>{value?"✓":""}</i><span>{children}</span></label>; }
