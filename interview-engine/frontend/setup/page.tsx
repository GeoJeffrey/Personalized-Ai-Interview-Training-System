"use client";
import { useState, useEffect, useRef, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { submitAnswer, endSession, getSession } from "@/lib/api";
import { useVoice } from "@/lib/useVoice";
import { useTTS } from "@/lib/useTTS";
import {
  Mic, MicOff, Send, StopCircle, ChevronRight,
  BarChart3, AlertTriangle, Loader2, Volume2,
} from "lucide-react";

/* ── Types ──────────────────────────────────────────────────────────────── */
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

/* ── Waveform visual ─────────────────────────────────────────────────────── */
function Waveform() {
  return (
    <div className="flex items-center gap-0.5 h-5">
      {[1,2,3,4,5].map(i => (
        <div key={i} className="wave-bar w-1 h-full bg-red-400 rounded-full origin-bottom" />
      ))}
    </div>
  );
}

/* ── Score badge ─────────────────────────────────────────────────────────── */
function ScoreBadge({ score }: { score: number }) {
  const color = score >= 7 ? "text-green-400" : score >= 5 ? "text-yellow-400" : "text-red-400";
  return <span className={`text-xs font-bold ${color}`}>{score}/10</span>;
}

/* ── Filler pill ─────────────────────────────────────────────────────────── */
function FillerPills({ fillers }: { fillers: Record<string, number> }) {
  const entries = Object.entries(fillers).slice(0, 4);
  if (!entries.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {entries.map(([word, count]) => (
        <span key={word} className="bg-amber-900/40 border border-amber-700 text-amber-300 rounded px-1.5 py-0.5 text-xs">
          "{word}" ×{count}
        </span>
      ))}
    </div>
  );
}

/* ── Main interview component ────────────────────────────────────────────── */
function InterviewContent() {
  const router       = useRouter();
  const params       = useSearchParams();
  const sessionId    = Number(params.get("sid"));

  const [session, setSession]     = useState<SessionMeta | null>(null);
  const [messages, setMessages]   = useState<ChatMessage[]>([]);
  const [input, setInput]         = useState("");
  const [status, setStatus]       = useState<"idle"|"speaking"|"waiting"|"ended">("idle");
  const [currentQ, setCurrentQ]   = useState(0);
  const [totalQ, setTotalQ]       = useState(0);
  const [error, setError]         = useState("");
  const [ending, setEnding]       = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { speak, stop: stopTTS } = useTTS();

  /* ── Voice hook ──────────────────────────────────────────────────────── */
  const { state: voiceState, interimText, startListening, stopListening } = useVoice({
    onTranscript: (text) => {
      setInput(text);
    },
    onError: (msg) => setError(msg),
  });

  /* ── Load session from localStorage + backend ────────────────────────── */
  useEffect(() => {
    const raw = localStorage.getItem("ie_session");
    if (!raw || !sessionId) { router.push("/setup"); return; }
    const s: SessionMeta = JSON.parse(raw);
    setSession(s);
    setTotalQ(s.questions?.length || 0);

    // Add opening message
    const opening: ChatMessage = {
      id: "open", role: "interviewer", content: s.opening_message,
    };
    // Add first question
    const firstQ: ChatMessage = {
      id: "q0", role: "interviewer",
      content: s.questions?.[0]?.question || "Tell me about yourself.",
    };
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

    const candidateMsg: ChatMessage = {
      id: `c-${Date.now()}`, role: "candidate", content: text,
    };
    setMessages(prev => [...prev, candidateMsg]);

    try {
      const res = await submitAnswer({ session_id: sessionId, answer_text: text });

      // Update candidate message with score & fillers
      setMessages(prev => prev.map(m =>
        m.id === candidateMsg.id
          ? { ...m, score: res.scoring?.score, feedback: res.scoring?.one_line_feedback, fillers: res.filler_stats?.found }
          : m
      ));

      // Add interviewer response
      const interviewerMsg: ChatMessage = {
        id: `i-${Date.now()}`, role: "interviewer", content: res.interviewer_message,
      };
      setMessages(prev => [...prev, interviewerMsg]);
      speak(res.interviewer_message);

      setCurrentQ(res.current_q_index || 0);

      if (res.action === "end_interview") {
        setStatus("ended");
      } else {
        setStatus("idle");
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Something went wrong.");
      setStatus("idle");
    }
  }, [sessionId, status, speak, stopTTS]);

  /* ── Mic toggle ──────────────────────────────────────────────────────── */
  const handleMic = useCallback(() => {
    if (voiceState === "idle") {
      setInput(""); startListening();
    } else {
      stopListening();
      // voice hook will call onTranscript → setInput; we submit after a tick
      setTimeout(() => {
        const finalText = input;  // captured at stop time via ref below
        // We use a ref for the latest input value
      }, 500);
    }
  }, [voiceState, startListening, stopListening, input]);

  // Auto-submit after voice stops
  const prevVoiceState = useRef(voiceState);
  const inputRef = useRef(input);
  inputRef.current = input;
  useEffect(() => {
    if (prevVoiceState.current === "processing" && voiceState === "idle") {
      const text = inputRef.current;
      if (text.trim()) handleSubmit(text);
    }
    prevVoiceState.current = voiceState;
  }, [voiceState, handleSubmit]);

  /* ── End interview ───────────────────────────────────────────────────── */
  async function handleEnd() {
    if (ending) return;
    setEnding(true);
    try {
      await endSession(sessionId);
      router.push(`/dashboard?sid=${sessionId}`);
    } catch { setEnding(false); }
  }

  /* ── Render ──────────────────────────────────────────────────────────── */
  const isStress = session && localStorage.getItem("ie_session")
    ? JSON.parse(localStorage.getItem("ie_session")!).mode === "stress"
    : false;

  return (
    <div className="flex flex-col h-screen max-w-2xl mx-auto">

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className={`flex items-center justify-between px-4 py-3 border-b
        ${isStress ? "border-red-900 bg-red-950/20" : "border-gray-800 bg-gray-950"}`}>
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full ${status === "ended" ? "bg-gray-500" : "bg-green-400 animate-pulse"}`} />
          <span className="text-sm font-medium text-gray-300">
            {status === "ended" ? "Interview complete" : isStress ? "⚡ Stress Interview" : "Mock Interview"}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">
            Q {Math.min(currentQ + 1, totalQ)} / {totalQ}
          </span>
          <button onClick={handleEnd} disabled={ending}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-red-400 transition-colors bg-gray-800 hover:bg-gray-700 px-3 py-1.5 rounded-lg">
            {ending ? <Loader2 className="w-3 h-3 animate-spin" /> : <StopCircle className="w-3 h-3" />}
            End & Report
          </button>
        </div>
      </header>

      {/* ── Progress bar ────────────────────────────────────────────────── */}
      <div className="h-0.5 bg-gray-800">
        <div
          className="h-full bg-indigo-500 transition-all duration-500"
          style={{ width: `${totalQ ? (currentQ / totalQ) * 100 : 0}%` }}
        />
      </div>

      {/* ── Chat area ───────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {messages.map(msg => (
          <div key={msg.id} className={`flex ${msg.role === "candidate" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm
              ${msg.role === "interviewer"
                ? "bg-gray-800 text-gray-100 rounded-tl-sm"
                : "bg-indigo-600 text-white rounded-tr-sm"}`}>

              {msg.role === "interviewer" && (
                <div className="flex items-center gap-1.5 mb-1.5">
                  <Volume2 className="w-3 h-3 text-indigo-400" />
                  <span className="text-xs text-indigo-400 font-medium">Interviewer</span>
                </div>
              )}

              <p className="leading-relaxed">{msg.content}</p>

              {/* Score & feedback for candidate messages */}
              {msg.role === "candidate" && msg.score !== undefined && (
                <div className="mt-2 pt-2 border-t border-indigo-500/40 space-y-1">
                  <div className="flex items-center gap-2">
                    <ScoreBadge score={msg.score} />
                    {msg.feedback && <span className="text-xs text-indigo-200">{msg.feedback}</span>}
                  </div>
                  {msg.fillers && Object.keys(msg.fillers).length > 0 && (
                    <FillerPills fillers={msg.fillers} />
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Interim voice text */}
        {interimText && (
          <div className="flex justify-end">
            <div className="max-w-[85%] bg-indigo-900/50 border border-indigo-700 rounded-2xl rounded-tr-sm px-4 py-3">
              <p className="text-sm text-indigo-300 italic">{interimText}…</p>
            </div>
          </div>
        )}

        {/* Waiting indicator */}
        {status === "waiting" && (
          <div className="flex justify-start">
            <div className="bg-gray-800 rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-2">
              <Loader2 className="w-4 h-4 text-indigo-400 animate-spin" />
              <span className="text-sm text-gray-400">Thinking…</span>
            </div>
          </div>
        )}

        {/* Interview ended banner */}
        {status === "ended" && (
          <div className="bg-green-950/40 border border-green-800 rounded-2xl p-4 text-center space-y-3">
            <p className="text-green-300 font-medium">🎉 Interview complete!</p>
            <button onClick={handleEnd} disabled={ending}
              className="bg-green-600 hover:bg-green-500 px-6 py-2.5 rounded-xl text-sm font-semibold flex items-center gap-2 mx-auto">
              {ending ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}
              View Full Report
            </button>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 text-red-400 text-xs bg-red-950/30 border border-red-800 rounded-xl px-3 py-2">
            <AlertTriangle className="w-3 h-3" /> {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ───────────────────────────────────────────────────── */}
      {status !== "ended" && (
        <div className="border-t border-gray-800 bg-gray-950 px-4 py-4">
          <div className="flex items-end gap-3">
            {/* Mic button */}
            <button
              onClick={handleMic}
              disabled={status === "waiting"}
              className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 transition-all
                ${voiceState === "listening"
                  ? "bg-red-600 mic-pulse"
                  : voiceState === "processing"
                  ? "bg-amber-600"
                  : "bg-gray-800 hover:bg-gray-700"}`}
            >
              {voiceState === "listening"
                ? <Waveform />
                : voiceState === "processing"
                ? <Loader2 className="w-4 h-4 animate-spin text-white" />
                : <Mic className="w-4 h-4 text-gray-300" />}
            </button>

            {/* Text input */}
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(input);
                }
              }}
              placeholder={
                voiceState === "listening" ? "Listening… speak now" :
                status === "waiting"       ? "Waiting for response…" :
                "Type your answer or press the mic to speak"
              }
              disabled={status === "waiting" || voiceState !== "idle"}
              rows={2}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-sm resize-none focus:outline-none focus:border-indigo-500 placeholder-gray-600 disabled:opacity-50"
            />

            {/* Send button */}
            <button
              onClick={() => handleSubmit(input)}
              disabled={!input.trim() || status === "waiting"}
              className="w-11 h-11 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-30 flex items-center justify-center shrink-0 transition-colors"
            >
              <Send className="w-4 h-4 text-white" />
            </button>
          </div>

          <p className="text-xs text-gray-600 mt-2 text-center">
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
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-indigo-400" />
      </div>
    }>
      <InterviewContent />
    </Suspense>
  );
}