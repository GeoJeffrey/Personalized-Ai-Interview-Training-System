"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

export default function SetupPage() {
  const router = useRouter();
  const [user, setUser]           = useState<any>(null);
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [jdFile, setJdFile]       = useState<File | null>(null);
  const [resumeDoc, setResumeDoc] = useState<any>(null);
  const [jdDoc, setJdDoc]         = useState<any>(null);
  const [mode, setMode]           = useState<"standard" | "stress">("standard");
  const [numQ, setNumQ]           = useState(8);
  const [title, setTitle]         = useState("");
  const [uploading, setUploading] = useState<"resume"|"jd"|null>(null);
  const [starting, setStarting]   = useState(false);
  const [error, setError]         = useState("");

  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    const u = localStorage.getItem("ie_user");
    if (!u) { router.push("/"); return; }
    setUser(JSON.parse(u));
  }, [router]);

  /* ── Upload file ──────────────────────────────────────────────────────── */
  async function handleUpload(file: File, docType: "resume" | "jd") {
    if (!user) return;
    setUploading(docType); setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("user_id", String(user.user_id));
      form.append("doc_type", docType);

      const res = await fetch(`${API}/api/upload/document`, {
        method: "POST", body: form,
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Upload failed");
      }
      const data = await res.json();
      if (docType === "resume") setResumeDoc(data);
      else setJdDoc(data);
    } catch (e: any) {
      setError(e.message || "Upload failed");
    } finally { setUploading(null); }
  }

  /* ── Start interview ──────────────────────────────────────────────────── */
  async function handleStart() {
    if (!resumeDoc || !jdDoc) { setError("Upload both resume and job description first."); return; }
    setStarting(true); setError("");
    try {
      const res = await fetch(`${API}/api/interview/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id:       user.user_id,
          title:         title || `Interview – ${new Date().toLocaleDateString()}`,
          resume_text:   resumeDoc.text_preview,
          jd_text:       jdDoc.text_preview,
          mode,
          num_questions: numQ,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to create session");
      }
      const session = await res.json();
      localStorage.setItem("ie_session", JSON.stringify(session));
      router.push(`/interview?sid=${session.session_id}`);
    } catch (e: any) {
      setError(e.message || "Could not start interview");
    } finally { setStarting(false); }
  }

  /* ── Styles ───────────────────────────────────────────────────────────── */
  const s = {
    page:     { minHeight:"100vh", background:"#0d1117", color:"#f0f0f0", fontFamily:"sans-serif", padding:"40px 16px" },
    inner:    { maxWidth:480, margin:"0 auto" },
    heading:  { fontSize:22, fontWeight:"bold", marginBottom:4 },
    sub:      { color:"#6b7280", fontSize:14, marginBottom:28 },
    zone:     (active: boolean) => ({ border:`2px dashed ${active?"#4ade80":"#30363d"}`, borderRadius:14, padding:24, textAlign:"center" as const, cursor:"pointer", background: active?"rgba(74,222,128,0.05)":"#161b27", marginBottom:12, transition:"all .2s" }),
    label:    { fontSize:13, color:"#9ca3af", marginBottom:6, display:"block" },
    input:    { width:"100%", background:"#161b27", border:"1px solid #30363d", borderRadius:10, padding:"10px 14px", color:"#f0f0f0", fontSize:14, outline:"none", boxSizing:"border-box" as const, marginBottom:12 },
    modeBtn:  (active: boolean, stress: boolean) => ({ flex:1, padding:"10px", borderRadius:10, border:`1px solid ${active?(stress?"#ef4444":"#6366f1"):"#30363d"}`, background: active?(stress?"rgba(239,68,68,0.1)":"rgba(99,102,241,0.1)"):"transparent", color: active?(stress?"#f87171":"#a5b4fc"):"#9ca3af", cursor:"pointer", fontWeight: active?"600":"400", fontSize:14 }),
    startBtn: { width:"100%", background: starting||!resumeDoc||!jdDoc?"#374151":"#6366f1", color:"#fff", border:"none", borderRadius:12, padding:"14px", fontSize:16, fontWeight:"600", cursor: starting||!resumeDoc||!jdDoc?"not-allowed":"pointer", marginTop:8 },
    error:    { color:"#f87171", fontSize:13, background:"rgba(239,68,68,0.1)", border:"1px solid #7f1d1d", borderRadius:8, padding:"10px 14px", marginBottom:12 },
    success:  { color:"#4ade80", fontSize:13, background:"rgba(74,222,128,0.1)", border:"1px solid #166534", borderRadius:8, padding:"10px 14px", marginBottom:12 },
  };

  return (
    <div style={s.page}>
      <div style={s.inner}>
        <h1 style={s.heading}>Set up your interview</h1>
        <p style={s.sub}>Upload your documents and configure your session.</p>

        {/* Resume upload */}
        <div
          style={s.zone(!!resumeDoc)}
          onClick={() => !resumeDoc && document.getElementById("resume-input")?.click()}
        >
          <input id="resume-input" type="file" accept=".pdf,.docx,.txt" hidden
            onChange={e => { const f = e.target.files?.[0]; if(f) handleUpload(f,"resume"); }} />
          {uploading==="resume" ? <p style={{color:"#6366f1",margin:0}}>⏳ Parsing resume…</p>
          : resumeDoc ? <p style={{color:"#4ade80",margin:0}}>✅ {resumeDoc.filename} ({resumeDoc.char_count} chars)</p>
          : <p style={{color:"#6b7280",margin:0}}>📄 Click to upload <strong>Resume</strong> (PDF, DOCX, TXT)</p>}
        </div>

        {/* JD upload */}
        <div
          style={s.zone(!!jdDoc)}
          onClick={() => !jdDoc && document.getElementById("jd-input")?.click()}
        >
          <input id="jd-input" type="file" accept=".pdf,.docx,.txt" hidden
            onChange={e => { const f = e.target.files?.[0]; if(f) handleUpload(f,"jd"); }} />
          {uploading==="jd" ? <p style={{color:"#6366f1",margin:0}}>⏳ Parsing job description…</p>
          : jdDoc ? <p style={{color:"#4ade80",margin:0}}>✅ {jdDoc.filename} ({jdDoc.char_count} chars)</p>
          : <p style={{color:"#6b7280",margin:0}}>💼 Click to upload <strong>Job Description</strong> (PDF, DOCX, TXT)</p>}
        </div>

        {/* Settings */}
        <div style={{background:"#161b27", border:"1px solid #30363d", borderRadius:14, padding:20, marginBottom:16}}>
          <p style={{fontSize:12, color:"#6b7280", textTransform:"uppercase", letterSpacing:1, marginBottom:16, marginTop:0}}>Settings</p>

          {/* Title */}
          <label style={s.label}>Session title (optional)</label>
          <input style={s.input} placeholder={`Interview – ${new Date().toLocaleDateString()}`}
            value={title} onChange={e=>setTitle(e.target.value)} />

          {/* Questions */}
          <label style={s.label}>Questions: <strong style={{color:"#f0f0f0"}}>{numQ}</strong></label>
          <input type="range" min={4} max={15} value={numQ} onChange={e=>setNumQ(+e.target.value)}
            style={{width:"100%", marginBottom:16, accentColor:"#6366f1"}} />

          {/* Mode */}
          <label style={s.label}>Interview mode</label>
          <div style={{display:"flex", gap:8}}>
            <button onClick={()=>setMode("standard")} style={s.modeBtn(mode==="standard",false)}>🧠 Standard</button>
            <button onClick={()=>setMode("stress")}   style={s.modeBtn(mode==="stress",true)}>⚡ Stress</button>
          </div>
          {mode==="stress" && <p style={{color:"#f87171",fontSize:12,marginTop:8,marginBottom:0}}>⚠️ AI will aggressively challenge every answer.</p>}
        </div>

        {error && <div style={s.error}>{error}</div>}

        <button onClick={handleStart} disabled={starting||!resumeDoc||!jdDoc} style={s.startBtn}>
          {starting ? "⏳ Generating questions…" : "Start Interview →"}
        </button>
      </div>
    </div>
  );
}
