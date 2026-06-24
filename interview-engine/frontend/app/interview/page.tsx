"use client";
import { useState, useEffect, useRef, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { submitAnswer, endSession } from "../../lib/api";
import { useVoice } from "../../lib/useVoice";
import { useTTS } from "../../lib/useTTS";
import {
  Mic, Send, StopCircle,
  BarChart3, AlertTriangle, Loader2, Volume2,
} from "lucide-react";

/* ── Types ─────────────────────────────────────────────────────────────── */
interface ChatMessage {
  id:       string;
  role:     "interviewer" | "candidate";
  content:  string;
  score?:   number;
  feedback?: string;
  fillers?:  Record<string, number>;
}

interface SessionMeta {
  session_id:      number;
  opening_message: string;
  questions:       Array<{ question: string; type: string; topic: string }>;
}

/* ── Waveform ───────────────────────────────────────────────────────────── */
function Waveform() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2, height: 20 }}>
      {[1,2,3,4,5].map(i => (
        <div key={i} style={{
          width: 3, height: "100%", background: "#f87171",
          borderRadius: 2, animation: `wave 1s ease-in-out ${i * 0.1}s infinite`,
        }} />
      ))}
      <style>{`@keyframes wave { 0%,100%{transform:scaleY(.4)} 50%{transform:scaleY(1)} }`}</style>
    </div>
  );
}

/* ── Main ───────────────────────────────────────────────────────────────── */
function InterviewContent() {
  const router    = useRouter();
  const params    = useSearchParams();
  const sessionId = Number(params.get("sid"));

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input,    setInput]    = useState("");
  const [status,   setStatus]   = useState<"idle"|"waiting"|"ended">("idle");
  const [currentQ, setCurrentQ] = useState(0);
  const [totalQ,   setTotalQ]   = useState(0);
  const [error,    setError]    = useState("");
  const [ending,   setEnding]   = useState(false);
  const [isStress, setIsStress] = useState(false);
  const bottomRef  = useRef<HTMLDivElement>(null);
  const inputRef   = useRef("");
  inputRef.current = input;

  const { speak, stop: stopTTS } = useTTS();
  const prevVoiceState = useRef<string>("idle");

  const { state: voiceState, interimText, startListening, stopListening } = useVoice({
    onTranscript: (text) => setInput(text),
    onError:      (msg)  => setError(msg),
  });

  /* ── Load session ────────────────────────────────────────────────────── */
  useEffect(() => {
    const raw = localStorage.getItem("ie_session");
    if (!raw || !sessionId) { router.push("/setup"); return; }
    const s: SessionMeta = JSON.parse(raw);
    setTotalQ(s.questions?.length || 0);
    setIsStress(JSON.parse(raw).mode === "stress");

    const opening: ChatMessage = { id: "open", role: "interviewer", content: s.opening_message };
    const firstQ:  ChatMessage = { id: "q0",   role: "interviewer", content: s.questions?.[0]?.question || "Tell me about yourself." };
    setMessages([opening, firstQ]);
    speak(s.opening_message + " " + (s.questions?.[0]?.question || ""));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  /* ── Auto scroll ─────────────────────────────────────────────────────── */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, interimText]);

  /* ── Submit answer ───────────────────────────────────────────────────── */
  const handleSubmit = useCallback(async (text: string) => {
    if (!text.trim() || status === "waiting" || !sessionId) return;
    setInput(""); setError(""); setStatus("waiting");
    stopTTS();

    const candidateMsg: ChatMessage = { id: `c-${Date.now()}`, role: "candidate", content: text };
    setMessages(prev => [...prev, candidateMsg]);

    try {
      const res = await submitAnswer(sessionId, text);

      setMessages(prev => prev.map(m =>
        m.id === candidateMsg.id
          ? { ...m, score: res.scoring?.score, feedback: res.scoring?.one_line_feedback, fillers: res.filler_stats?.found }
          : m
      ));

      const interviewerMsg: ChatMessage = { id: `i-${Date.now()}`, role: "interviewer", content: res.interviewer_message };
      setMessages(prev => [...prev, interviewerMsg]);
      speak(res.interviewer_message);
      setCurrentQ(res.current_q_index || 0);
      setStatus(res.action === "end_interview" ? "ended" : "idle");
    } catch (e: any) {
      setError(e?.message || "Something went wrong.");
      setStatus("idle");
    }
  }, [sessionId, status, speak, stopTTS]);

  /* ── Auto-submit after voice stops ──────────────────────────────────── */
  useEffect(() => {
    if (prevVoiceState.current === "processing" && voiceState === "idle") {
      const text = inputRef.current;
      if (text.trim()) handleSubmit(text);
    }
    prevVoiceState.current = voiceState;
  }, [voiceState, handleSubmit]);

  /* ── End session ─────────────────────────────────────────────────────── */
  async function handleEnd() {
    if (ending) return;
    setEnding(true);
    try {
      await endSession(sessionId);
      router.push(`/dashboard?sid=${sessionId}`);
    } catch { setEnding(false); }
  }

  /* ── Mic toggle ──────────────────────────────────────────────────────── */
  function handleMic() {
    if (voiceState === "idle") { setInput(""); startListening(); }
    else stopListening();
  }

  /* ── Styles ──────────────────────────────────────────────────────────── */
  const s = {
    root:     { display:"flex", flexDirection:"column" as const, height:"100vh", maxWidth:680, margin:"0 auto", background:"#0d1117", color:"#f0f0f0", fontFamily:"sans-serif" },
    header:   { display:"flex", alignItems:"center", justifyContent:"space-between", padding:"12px 16px", borderBottom:`1px solid ${isStress?"#7f1d1d":"#21262d"}`, background: isStress?"rgba(127,29,29,0.15)":"#0d1117" },
    dot:      { width:8, height:8, borderRadius:"50%", background: status==="ended"?"#6b7280":"#4ade80", animation: status==="ended"?"none":"pulse 2s infinite" },
    progress: { height:2, background:"#21262d" },
    bar:      { height:"100%", background:"#6366f1", width:`${totalQ?(currentQ/totalQ)*100:0}%`, transition:"width .5s" },
    chat:     { flex:1, overflowY:"auto" as const, padding:"24px 16px", display:"flex", flexDirection:"column" as const, gap:16 },
    endBtn:   { display:"flex", alignItems:"center", gap:6, fontSize:12, color:"#9ca3af", background:"#21262d", border:"none", borderRadius:8, padding:"6px 12px", cursor:"pointer" },
    inputBar: { borderTop:"1px solid #21262d", padding:"16px", background:"#0d1117" },
    inputRow: { display:"flex", alignItems:"flex-end", gap:12 },
    micBtn:   { width:44, height:44, borderRadius:10, border:"none", cursor:"pointer", display:"flex", alignItems:"center", justifyContent:"center", flexShrink:0, background: voiceState==="listening"?"#dc2626": voiceState==="processing"?"#d97706":"#21262d" },
    textarea: { flex:1, background:"#161b27", border:"1px solid #30363d", borderRadius:10, padding:"12px 16px", color:"#f0f0f0", fontSize:14, resize:"none" as const, outline:"none", fontFamily:"sans-serif" },
    sendBtn:  { width:44, height:44, borderRadius:10, background:"#6366f1", border:"none", cursor:"pointer", display:"flex", alignItems:"center", justifyContent:"center", flexShrink:0, opacity: !input.trim()||status==="waiting"?0.3:1 },
  };

  return (
    <div style={s.root}>
      {/* Header */}
      <header style={s.header}>
        <div style={{ display:"flex", alignItems:"center", gap:10 }}>
          <div style={s.dot} />
          <span style={{ fontSize:14, color:"#d1d5db" }}>
            {status==="ended" ? "Interview complete" : isStress ? "⚡ Stress Interview" : "Mock Interview"}
          </span>
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:12 }}>
          <span style={{ fontSize:12, color:"#6b7280" }}>Q {Math.min(currentQ+1,totalQ)} / {totalQ}</span>
          <button onClick={handleEnd} disabled={ending} style={s.endBtn}>
            {ending ? <Loader2 size={12} /> : <StopCircle size={12} />} End & Report
          </button>
        </div>
      </header>

      {/* Progress */}
      <div style={s.progress}><div style={s.bar} /></div>

      {/* Chat */}
      <div style={s.chat}>
        {messages.map(msg => (
          <div key={msg.id} style={{ display:"flex", justifyContent: msg.role==="candidate"?"flex-end":"flex-start" }}>
            <div style={{
              maxWidth:"85%", borderRadius:16, padding:"12px 16px", fontSize:14,
              background: msg.role==="interviewer"?"#161b27":"#6366f1",
              color: "#f0f0f0",
              borderTopLeftRadius:  msg.role==="interviewer"?4:16,
              borderTopRightRadius: msg.role==="candidate"?4:16,
            }}>
              {msg.role==="interviewer" && (
                <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:6, color:"#818cf8", fontSize:12 }}>
                  <Volume2 size={12}/> Interviewer
                </div>
              )}
              <p style={{ margin:0, lineHeight:1.6 }}>{msg.content}</p>
              {msg.role==="candidate" && msg.score!==undefined && (
                <div style={{ marginTop:8, paddingTop:8, borderTop:"1px solid rgba(255,255,255,0.15)", fontSize:12 }}>
                  <span style={{ color: msg.score>=7?"#4ade80":msg.score>=5?"#fbbf24":"#f87171", fontWeight:"bold" }}>
                    {msg.score}/10
                  </span>
                  {msg.feedback && <span style={{ marginLeft:8, color:"#c7d2fe" }}>{msg.feedback}</span>}
                  {msg.fillers && Object.keys(msg.fillers).length>0 && (
                    <div style={{ display:"flex", flexWrap:"wrap", gap:4, marginTop:6 }}>
                      {Object.entries(msg.fillers).slice(0,4).map(([w,c])=>(
                        <span key={w} style={{ background:"rgba(217,119,6,0.2)", border:"1px solid #92400e", color:"#fcd34d", borderRadius:4, padding:"2px 6px", fontSize:11 }}>
                          "{w}" ×{c}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {interimText && (
          <div style={{ display:"flex", justifyContent:"flex-end" }}>
            <div style={{ background:"rgba(99,102,241,0.2)", border:"1px solid #4f46e5", borderRadius:16, borderTopRightRadius:4, padding:"10px 14px", fontSize:14, color:"#a5b4fc", fontStyle:"italic" }}>
              {interimText}…
            </div>
          </div>
        )}

        {status==="waiting" && (
          <div style={{ display:"flex", justifyContent:"flex-start" }}>
            <div style={{ background:"#161b27", borderRadius:16, borderTopLeftRadius:4, padding:"10px 16px", display:"flex", alignItems:"center", gap:8, color:"#9ca3af", fontSize:14 }}>
              <Loader2 size={16} style={{ animation:"spin 1s linear infinite" }} /> Thinking…
              <style>{`@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}`}</style>
            </div>
          </div>
        )}

        {status==="ended" && (
          <div style={{ background:"rgba(20,83,45,0.3)", border:"1px solid #166534", borderRadius:16, padding:20, textAlign:"center" }}>
            <p style={{ color:"#86efac", margin:"0 0 12px" }}>🎉 Interview complete!</p>
            <button onClick={handleEnd} disabled={ending} style={{ background:"#16a34a", color:"#fff", border:"none", borderRadius:10, padding:"10px 24px", cursor:"pointer", fontWeight:600, display:"inline-flex", alignItems:"center", gap:8 }}>
              <BarChart3 size={16}/> View Full Report
            </button>
          </div>
        )}

        {error && (
          <div style={{ display:"flex", alignItems:"center", gap:8, color:"#f87171", fontSize:12, background:"rgba(127,29,29,0.2)", border:"1px solid #7f1d1d", borderRadius:10, padding:"8px 12px" }}>
            <AlertTriangle size={12}/> {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      {status!=="ended" && (
        <div style={s.inputBar}>
          <div style={s.inputRow}>
            <button onClick={handleMic} disabled={status==="waiting"} style={s.micBtn}>
              {voiceState==="listening" ? <Waveform /> : voiceState==="processing" ? <Loader2 size={16} color="#fff"/> : <Mic size={16} color="#d1d5db"/>}
            </button>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if(e.key==="Enter"&&!e.shiftKey){ e.preventDefault(); handleSubmit(input); } }}
              placeholder={voiceState==="listening"?"Listening… speak now": status==="waiting"?"Waiting for response…":"Type your answer or press mic to speak"}
              disabled={status==="waiting"||voiceState!=="idle"}
              rows={2}
              style={s.textarea}
            />
            <button onClick={()=>handleSubmit(input)} disabled={!input.trim()||status==="waiting"} style={s.sendBtn}>
              <Send size={16} color="#fff"/>
            </button>
          </div>
          <p style={{ textAlign:"center", fontSize:11, color:"#4b5563", marginTop:8 }}>
            Press mic to speak · Enter to send · Shift+Enter for new line
          </p>
        </div>
      )}
    </div>
  );
}

export default function InterviewPage() {
  return (
    <Suspense fallback={
      <div style={{ display:"flex", height:"100vh", alignItems:"center", justifyContent:"center", background:"#0d1117" }}>
        <Loader2 size={32} color="#6366f1" style={{ animation:"spin 1s linear infinite" }}/>
        <style>{`@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}`}</style>
      </div>
    }>
      <InterviewContent />
    </Suspense>
  );
}
