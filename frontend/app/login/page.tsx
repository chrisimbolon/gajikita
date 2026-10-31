"use client";
import Wordmark from "@/components/Wordmark";
import { useAuth } from "@/context/AuthContext";
import { Loader2, LogIn } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
    } catch {
      setError("Email atau kata sandi salah.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ width: "100%", maxWidth: 380 }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 24 }}><Wordmark size={26} /></div>
        <div className="card">
          <h1 className="display" style={{ fontSize: 24, marginBottom: 6, textTransform: "none" }}>Masuk</h1>
          <p style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 22 }}>Masuk ke akun perusahaan Anda.</p>
          {error && (
            <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>{error}</div>
          )}
          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 16 }}>
              <label className="label" htmlFor="email">Email</label>
              <input id="email" className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="anda@perusahaan.com" />
            </div>
            <div style={{ marginBottom: 22 }}>
              <label className="label" htmlFor="password">Kata Sandi</label>
              <input id="password" className="input" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
            </div>
            <button className="btn-rust" type="submit" disabled={loading} style={{ width: "100%", justifyContent: "center", padding: "11px 0" }}>
              {loading ? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> : <LogIn size={16} />} Masuk
            </button>
          </form>
        </div>
        <p style={{ textAlign: "center", fontSize: 13.5, color: "var(--steel)", marginTop: 20 }}>
          Belum punya akun? <Link href="/register" style={{ color: "var(--rust)", fontWeight: 600 }}>Daftarkan perusahaan Anda</Link>
        </p>
      </div>
    </div>
  );
}
