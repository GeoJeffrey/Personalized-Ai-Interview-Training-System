/**
 * useTTS.ts — Text-to-speech hook
 *
 * Uses the browser's SpeechSynthesis API — completely free, no API key.
 * Picks the best available English voice automatically.
 *
 * Usage:
 *   const { speak, stop, isSpeaking, voices } = useTTS()
 *   speak("Hello, tell me about yourself.", { rate: 0.95, onEnd: () => console.log("done") })
 */
"use client";
import { useState, useEffect, useRef, useCallback } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SpeakOptions {
  rate?:   number;    // 0.1 – 10,  default 0.95
  pitch?:  number;    // 0   – 2,   default 1.0
  volume?: number;    // 0   – 1,   default 1.0
  lang?:   string;    // default "en-US"
  onEnd?:  () => void;
  onStart?: () => void;
}

export interface UseTTSReturn {
  speak:      (text: string, opts?: SpeakOptions) => void;
  stop:       () => void;
  isSpeaking: boolean;
  isSupported: boolean;
  voices:     SpeechSynthesisVoice[];   // available voices (useful for a voice picker)
}

// ── Voice preference order ────────────────────────────────────────────────────
// Sorted by quality — first match wins.
const PREFERRED_VOICE_KEYWORDS = [
  "google us english",
  "google uk english female",
  "google uk english male",
  "microsoft aria",
  "microsoft guy",
  "samantha",             // macOS high-quality voice
  "karen",
  "daniel",
];

function pickVoice(voices: SpeechSynthesisVoice[], lang: string): SpeechSynthesisVoice | null {
  // 1. Try preferred voices by name
  for (const keyword of PREFERRED_VOICE_KEYWORDS) {
    const match = voices.find((v) => v.name.toLowerCase().includes(keyword));
    if (match) return match;
  }
  // 2. Any local (non-network) voice in the requested lang
  const local = voices.find((v) => v.lang.startsWith(lang.split("-")[0]) && v.localService);
  if (local) return local;
  // 3. Any voice in the requested lang
  const any = voices.find((v) => v.lang.startsWith(lang.split("-")[0]));
  if (any) return any;
  // 4. First available voice
  return voices[0] ?? null;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useTTS(): UseTTSReturn {
  const [isSpeaking,  setIsSpeaking]  = useState(false);
  const [voices,      setVoices]      = useState<SpeechSynthesisVoice[]>([]);
  const [isSupported, setIsSupported] = useState(false);
  const utterRef = useRef<SpeechSynthesisUtterance | null>(null);

  // ── Load voices ────────────────────────────────────────────────────────────
  // Voices load asynchronously in most browsers — we listen for the event.
  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    setIsSupported(true);

    const load = () => {
      const v = window.speechSynthesis.getVoices();
      if (v.length) setVoices(v);
    };

    load();
    window.speechSynthesis.addEventListener("voiceschanged", load);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", load);
  }, []);

  // ── speak ──────────────────────────────────────────────────────────────────
  const speak = useCallback((text: string, opts: SpeakOptions = {}) => {
    if (!text.trim() || typeof window === "undefined" || !window.speechSynthesis) return;

    const {
      rate   = 0.95,
      pitch  = 1.0,
      volume = 1.0,
      lang   = "en-US",
      onEnd,
      onStart,
    } = opts;

    // Cancel any ongoing speech
    window.speechSynthesis.cancel();

    const utter     = new SpeechSynthesisUtterance(text);
    utterRef.current = utter;

    // Apply voice
    const currentVoices = window.speechSynthesis.getVoices();
    const voice = pickVoice(currentVoices.length ? currentVoices : voices, lang);
    if (voice) utter.voice = voice;

    utter.lang   = lang;
    utter.rate   = rate;
    utter.pitch  = pitch;
    utter.volume = volume;

    utter.onstart = () => { setIsSpeaking(true);  onStart?.(); };
    utter.onend   = () => { setIsSpeaking(false); onEnd?.();   };
    utter.onerror = (e) => {
      // "interrupted" is normal when stop() is called — not a real error
      if (e.error !== "interrupted") console.warn("TTS error:", e.error);
      setIsSpeaking(false);
    };

    // Chrome bug: SpeechSynthesis pauses after ~15s in some versions.
    // Fix: resume every 10 s while speaking.
    const resumeInterval = setInterval(() => {
      if (window.speechSynthesis.paused) window.speechSynthesis.resume();
    }, 10_000);
    utter.onend = () => {
      clearInterval(resumeInterval);
      setIsSpeaking(false);
      onEnd?.();
    };

    window.speechSynthesis.speak(utter);
  }, [voices]);

  // ── stop ───────────────────────────────────────────────────────────────────
  const stop = useCallback(() => {
    if (typeof window === "undefined") return;
    window.speechSynthesis.cancel();
    setIsSpeaking(false);
  }, []);

  return { speak, stop, isSpeaking, isSupported, voices };
}