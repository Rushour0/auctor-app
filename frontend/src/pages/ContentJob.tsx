import { useState } from "react";
import { getWorkspaceId } from "../auth/api";

export default function ContentJob() {
  const [workspaceId, setWorkspaceId] = useState(
    localStorage.getItem("auctor-workspace") || getWorkspaceId(),
  );
  const [fleetId, setFleetId] = useState("");
  const [clientId, setClientId] = useState("");
  const [topic, setTopic] = useState("AI agents and founder-led growth");
  const [job, setJob] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function start() {
    setLoading(true); setError("");
    try {
      const response = await fetch("/api/content-jobs", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({workspace_id:workspaceId,fleet_id:fleetId,client_id:clientId,topic})});
      if (!response.ok) throw new Error(await response.text());
      setJob(await response.json());
    } catch (reason) { setError(String(reason)); } finally { setLoading(false); }
  }
  async function approve() {
    if (!job?.approval_id) return;
    setLoading(true); setError("");
    try {
      const response = await fetch(`/api/content-jobs/approvals/${job.approval_id}/approve?workspace_id=${encodeURIComponent(workspaceId)}`, {method:"POST"});
      if (!response.ok) throw new Error(await response.text());
      setJob(await response.json());
    } catch (reason) { setError(String(reason)); } finally { setLoading(false); }
  }
  return <section style={{padding:24,maxWidth:900}}><h1>Run a content job</h1><p>Live research, a sourced draft and QA—then a hard stop for approval.</p><div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(180px,1fr))",gap:10}}><input aria-label="Workspace ID" value={workspaceId} onChange={e=>setWorkspaceId(e.target.value)} placeholder="Workspace ID"/><input aria-label="Fleet ID" value={fleetId} onChange={e=>setFleetId(e.target.value)} placeholder="Fleet ID"/><input aria-label="Client ID" value={clientId} onChange={e=>setClientId(e.target.value)} placeholder="Client ID"/><input aria-label="Topic" value={topic} onChange={e=>setTopic(e.target.value)} placeholder="Topic"/><button disabled={loading||!fleetId||!clientId||!topic} onClick={()=>void start()}>{loading?"Working…":"Research and draft"}</button></div>{error&&<p style={{color:"crimson"}}>{error}</p>}{job&&<div style={{marginTop:20,padding:18,background:"#f1f5f2",whiteSpace:"pre-wrap"}}><b>{job.status}</b>{job.draft&&<p>{job.draft}</p>}{job.status==="awaiting_approval"&&<button disabled={loading} onClick={()=>void approve()}>Approve and publish to web</button>}{job.post_url&&<p><a href={job.post_url}>Open published output ↗</a></p>}</div>}</section>;
}
