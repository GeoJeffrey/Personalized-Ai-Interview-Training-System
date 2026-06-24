/**
 * api.ts — All backend API calls
 * Single axios instance, typed responses, clean error handling.
 */
import axios, { AxiosError } from "axios";

declare const process: {
  env: {
    NEXT_PUBLIC_API_URL?: string;
  };
};

// ── Axios instance ────────────────────────────────────────────────────────────

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  timeout: 30_000,                        // 30s — Groq can be slow on first call
  headers: { "Content-Type": "application/json" },
});

// Unwrap error messages from FastAPI's { detail: "..." } format
api.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ detail?: string }>) => {
    const msg = err.response?.data?.detail || err.message || "Unknown error";
    return Promise.reject(new Error(msg));
  }
);

// ── Types ─────────────────────────────────────────────────────────────────────

export type InterviewMode = "standard" | "stress";
export type DocType       = "resume" | "jd" | "prep_material";

export interface User {
  user_id:  number;
  email:    string;
  name:     string;
  existing: boolean;
}

export interface Document {
  doc_id:       number;
  filename:     string;
  doc_type:     DocType;
  char_count:   number;
  token_est:    number;
  text_preview: string;
}

export interface Question {
  id:              number;
  question:        string;
  type:            "technical" | "behavioural" | "stress";
  topic:           string;
  difficulty:      "easy" | "medium" | "hard";
  follow_up_hint:  string;
}

export interface CreateSessionPayload {
  user_id:       number;
  title:         string;
  resume_text:   string;
  jd_text:       string;
  mode:          InterviewMode;
  num_questions: number;
  extra_context?: string;
}

export interface SessionCreated {
  session_id:      number;
  questions:       Question[];
  opening_message: string;
}

export interface AnswerResponse {
  action:               "ask_followup" | "next_question" | "end_interview";
  interviewer_message:  string;
  scoring: {
    score:              number;
    strengths:          string[];
    weaknesses:         string[];
    one_line_feedback:  string;
    model_answer_hint:  string;
  };
  filler_stats: {
    found:             Record<string, number>;
    total_fillers:     number;
    total_words:       number;
    filler_rate_pct:   number;
    fluency_score:     number;
  };
  current_q_index:  number;
  total_questions:  number;
}

export interface SessionReport {
  session: {
    id:            number;
    title:         string;
    mode:          InterviewMode;
    overall_score: number | null;
    started_at:    string;
    ended_at:      string | null;
  };
  analytics: {
    fluency_score:       number | null;
    avg_answer_quality:  number | null;
    filler_word_count:   number | null;
    filler_word_rate:    number | null;
    total_words:         number | null;
    skill_gaps:          Array<{ skill: string; severity: "high"|"medium"|"low"; advice: string }>;
    improvement_tips:    Array<{ tip: string; priority: "high"|"medium"|"low"; how: string }>;
    detailed_feedback:   string;
  };
  answer_scores: Array<{
    answer:      string;
    score:       number | null;
    feedback:    string | null;
    filler_words: Record<string, number> | null;
  }>;
}

export interface UserOverview {
  total_sessions:     number;
  completed_sessions: number;
  avg_score:          number | null;
  avg_fluency:        number | null;
  sessions: Array<{
    id:            number;
    title:         string;
    mode:          InterviewMode;
    status:        string;
    overall_score: number | null;
    started_at:    string;
    ended_at:      string | null;
    fluency_score: number | null;
    filler_rate:   number | null;
  }>;
}

// ── User ──────────────────────────────────────────────────────────────────────

export const createOrGetUser = (email: string, name: string): Promise<User> =>
  api.post("/api/session/user", { email, name }).then((r) => r.data);

// ── Upload ────────────────────────────────────────────────────────────────────

export const uploadDocument = (
  file: File,
  userId: number,
  docType: DocType,
  onProgress?: (pct: number) => void,
): Promise<Document> => {
  const form = new FormData();
  form.append("file",    file);
  form.append("user_id", String(userId));
  form.append("doc_type", docType);

  return api.post("/api/upload/document", form, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: onProgress
      ? (e) => onProgress(Math.round((e.loaded / (e.total ?? 1)) * 100))
      : undefined,
  }).then((r) => r.data);
};

export const listDocuments = (userId: number) =>
  api.get(`/api/upload/document/${userId}`).then((r) => r.data);

export const getDocumentText = (userId: number, docId: number): Promise<{ doc_id: number; text: string }> =>
  api.get(`/api/upload/document/${userId}/${docId}/text`).then((r) => r.data);

// ── Interview session ─────────────────────────────────────────────────────────

export const createSession = (payload: CreateSessionPayload): Promise<SessionCreated> =>
  api.post("/api/interview/session", payload).then((r) => r.data);

export const submitAnswer = (
  sessionId: number,
  answerText: string,
): Promise<AnswerResponse> =>
  api.post("/api/interview/answer", {
    session_id:  sessionId,
    answer_text: answerText,
  }).then((r) => r.data);

export const endSession = (sessionId: number): Promise<{ report: SessionReport["analytics"]; scores: number[] }> =>
  api.post(`/api/interview/session/${sessionId}/end`).then((r) => r.data);

export const getSession = (sessionId: number) =>
  api.get(`/api/interview/session/${sessionId}`).then((r) => r.data);

// ── Analytics ─────────────────────────────────────────────────────────────────

export const getUserOverview = (userId: number): Promise<UserOverview> =>
  api.get(`/api/analytics/user/${userId}/overview`).then((r) => r.data);

export const getSessionReport = (sessionId: number): Promise<SessionReport> =>
  api.get(`/api/analytics/session/${sessionId}/report`).then((r) => r.data);