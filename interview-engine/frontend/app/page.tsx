"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleStart(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) { setError("Enter your email to continue"); return; }
    setLoading(true); setError("");
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/session/user`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), name: name.trim() }),
      });
      if (!res.ok) throw new Error("Server error");
      const user = await res.json();
      localStorage.setItem("ie_user", JSON.stringify(user));
      router.push("/setup");
    } catch {
      setError("Could not connect to server. Is the backend running on port 8000?");
    } finally { setLoading(false); }
  }

  return (
    <main style={{
      minHeight: "100vh",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      background: "#0d1117",
      color: "#f0f0f0",
      fontFamily: "sans-serif",
      padding: "2rem",
    }}>
      <div style={{ textAlign: "center", marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "2.5rem", fontWeight: "bold", marginBottom: "0.5rem" }}>
          🎤 Interview Engine
        </h1>
        <p style={{ color: "#888", fontSize: "1rem" }}>
          AI mock interviews personalised to your resume. Powered by Groq.
        </p>
      </div>

      <form onSubmit={handleStart} style={{
        display: "flex", flexDirection: "column", gap: "1rem",
        width: "100%", maxWidth: "360px",
      }}>
        <input
          type="text"
          placeholder="Your name"
          value={name}
          onChange={e => setName(e.target.value)}
          style={inputStyle}
        />
        <input
          type="email"
          placeholder="Email address *"
          value={email}
          onChange={e => setEmail(e.target.value)}
          required
          style={inputStyle}
        />
        {error && <p style={{ color: "#f87171", fontSize: "0.85rem" }}>{error}</p>}
        <button type="submit" disabled={loading} style={btnStyle}>
          {loading ? "Connecting..." : "Get Started →"}
        </button>
      </form>
    </main>
  );
}

const inputStyle: React.CSSProperties = {
  background: "#161b27",
  border: "1px solid #30363d",
  borderRadius: "10px",
  padding: "0.75rem 1rem",
  color: "#f0f0f0",
  fontSize: "0.95rem",
  outline: "none",
};

const btnStyle: React.CSSProperties = {
  background: "#6366f1",
  color: "#fff",
  border: "none",
  borderRadius: "10px",
  padding: "0.85rem",
  fontSize: "1rem",
  fontWeight: "600",
  cursor: "pointer",
};
