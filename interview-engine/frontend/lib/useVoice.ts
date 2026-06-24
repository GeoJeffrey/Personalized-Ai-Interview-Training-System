/**
 * useVoice.ts — Speech-to-text hook
 *
 * Priority order:
 *   1. Deepgram WebSocket streaming  (if NEXT_PUBLIC_DEEPGRAM_KEY is set)
 *   2. Browser SpeechRecognition API (Chrome/Edge fallback, no key needed)
 *
 * Usage:
 *   const { state, interimText, finalText, startListening, stopListening, reset } = useVoice({ onTranscript })
 */
"use client";
import { useState, useRef, useCallback, useEffect } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

export type VoiceState =
  | "idle"         // mic is off
  | "listening"    // recording, waiting for speech
  | "processing"   // mic stopped, finalising transcript
  | "error";       // something went wrong

export interface UseVoiceOptions {
  onTranscript:  (text: string) => void;   // called with final text
  onInterim?:    (text: string) => void;   // called with live partial text
  onError?:      (msg: string)  => void;
  language?:     string;                   // default "en-US"
  silenceMs?:    number;                   // auto-stop after N ms of silence (Deepgram only)
}

export interface UseVoiceReturn {
  state:          VoiceState;
  interimText:    string;
  finalText:      string;
  startListening: () => Promise<void>;
  stopListening:  () => void;
  reset:          () => void;              // clear transcripts, go back to idle
  isDeepgram:     boolean;                // which backend is active
}

type SpeechRecognitionInstance = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  onresult: ((e: any) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: any) => void) | null;
  start: () => void;
  stop: () => void;
};

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useVoice({
  onTranscript,
  onInterim,
  onError,
  language   = "en-US",
  silenceMs  = 1500,
}: UseVoiceOptions): UseVoiceReturn {

  const [state,       setState]       = useState<VoiceState>("idle");
  const [interimText, setInterimText] = useState("");
  const [finalText,   setFinalText]   = useState("");

  const wsRef        = useRef<WebSocket | null>(null);
  const recorderRef  = useRef<MediaRecorder | null>(null);
  const streamRef    = useRef<MediaStream | null>(null);
  const finalRef     = useRef("");          // accumulates Deepgram final segments
  const silenceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const DEEPGRAM_KEY = typeof (globalThis as any).process !== "undefined"
    ? (globalThis as any).process.env?.NEXT_PUBLIC_DEEPGRAM_KEY
    : undefined;
  const isDeepgram   = Boolean(DEEPGRAM_KEY);

  // cleanup on unmount
  useEffect(() => () => { _cleanup(); }, []);

  // ── Internal helpers ───────────────────────────────────────────────────────

  function _cleanup() {
    clearTimeout(silenceTimer.current);
    recorderRef.current?.stop();
    wsRef.current?.close();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    recorderRef.current = null;
    wsRef.current       = null;
    streamRef.current   = null;
  }

  function _error(msg: string) {
    _cleanup();
    setState("error");
    setInterimText("");
    onError?.(msg);
    // auto-recover to idle after 3 s so the button is usable again
    setTimeout(() => setState("idle"), 3000);
  }

  function _finish(text: string) {
    _cleanup();
    const clean = text.trim();
    setFinalText(clean);
    setInterimText("");
    setState("idle");
    if (clean) onTranscript(clean);
  }

  // ── Deepgram path ──────────────────────────────────────────────────────────

  async function _startDeepgram() {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      _error("Microphone access denied. Allow mic in browser settings.");
      return;
    }

    streamRef.current = stream;
    finalRef.current  = "";
    setState("listening");
    setInterimText("");
    setFinalText("");

    const params = new URLSearchParams({
      model:       "nova-2",
      language,
      smart_format: "true",
      interim_results: "true",
      endpointing: String(silenceMs),
      utterance_end_ms: String(silenceMs + 500),
    });

    const ws = new WebSocket(
      `wss://api.deepgram.com/v1/listen?${params}`,
      ["token", DEEPGRAM_KEY!],
    );
    wsRef.current = ws;

    ws.onopen = () => {
      // pick the best supported mime type
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg"]
        .find((m) => MediaRecorder.isTypeSupported(m)) || "";

      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) ws.send(e.data);
      };
      recorder.start(200);   // 200 ms chunks — good balance of latency vs overhead
    };

    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data as string);

      // Utterance end → auto-stop (silence detected by Deepgram)
      if (data.type === "UtteranceEnd") {
        stopListening();
        return;
      }

      const alt        = data?.channel?.alternatives?.[0];
      const transcript = alt?.transcript ?? "";
      const isFinal    = data?.is_final ?? false;

      if (!transcript) return;

      if (isFinal) {
        finalRef.current += (finalRef.current ? " " : "") + transcript;
        setInterimText("");
        onInterim?.("");
      } else {
        setInterimText(transcript);
        onInterim?.(transcript);
      }
    };

    ws.onerror = () => _error("Voice connection failed. Check your Deepgram API key.");
    ws.onclose = (e) => {
      // code 1000 = normal close (we triggered it)
      if (e.code !== 1000 && state !== "idle") _error("Voice connection closed unexpectedly.");
    };
  }

  // ── Browser SpeechRecognition path ────────────────────────────────────────

  function _startBrowser() {
    const SR =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;

    if (!SR) {
      _error("Speech recognition not supported. Use Chrome or Edge.");
      return;
    }

    const rec = new SR() as SpeechRecognitionInstance;
    rec.continuous      = false;
    rec.interimResults  = true;
    rec.lang            = language;
    rec.maxAlternatives = 1;

    setState("listening");
    setInterimText("");
    setFinalText("");

    rec.onresult = (e) => {
      let interim = "";
      let final   = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) final   += t;
        else                       interim += t;
      }
      if (interim) { setInterimText(interim); onInterim?.(interim); }
      if (final)   { setFinalText(final); }
    };

    rec.onend = () => {
      setState("processing");
      setTimeout(() => {
        const text = finalText || finalRef.current;
        _finish(text);
      }, 150);
    };

    rec.onerror = (e) => {
      if (e.error === "no-speech") { _finish(""); return; }
      _error(`Speech error: ${e.error}`);
    };

    rec.start();

    // Store stop handle on recorderRef so stopListening() works
    (recorderRef as any).current = { stop: () => rec.stop() };
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  const startListening = useCallback(async () => {
    if (state !== "idle" && state !== "error") return;
    if (isDeepgram) await _startDeepgram();
    else             _startBrowser();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, isDeepgram]);

  const stopListening = useCallback(() => {
    if (state !== "listening") return;
    setState("processing");
    recorderRef.current?.stop();

    // Give Deepgram 600 ms to flush remaining transcripts before closing WS
    if (isDeepgram) {
      setTimeout(() => {
        wsRef.current?.close(1000);
        _finish(finalRef.current);
      }, 600);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, isDeepgram]);

  const reset = useCallback(() => {
    _cleanup();
    setState("idle");
    setInterimText("");
    setFinalText("");
    finalRef.current = "";
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { state, interimText, finalText, startListening, stopListening, reset, isDeepgram };
}