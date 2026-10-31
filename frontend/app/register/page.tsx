"use client";
import Wordmark from "@/components/Wordmark";
import { useAuth } from "@/context/AuthContext";
import { Loader2, UserPlus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

export default function RegisterPage() {
  const { register } = useAuth();
  const [form, setForm] = useState({ full_name: "", email: "", phone: "", password: "", organization_name: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await register(form);
    } catch (err) {
      const errors = (err as { response?: { data?: { errors?: Record<string, string[]> } } })?.response?.data?.errors;
      setError(errors ? Object.values(errors).flat().join(" ") : "Pendaftaran gagal. Coba lagi.");
    } finally {
      setLoading(false);
    }
  };

  const field = (k: keyof typeof form, label: string, type = "text", placeholder = "") => (
    <div style={{ marginBottom: 14 }}>
      <label className="label" htmlFor={k}>{label}</label>
      <input id={k} className="input" type={type} required={k !== "phone"} value={form[k]} onChange={set(k)} placeholder={placeholder} />
    </div>
  );

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ width: "100%", maxWidth: 420 }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 24 }}><Wordmark size={26} /></div>
        <div className="card">
          <h1 className="display" style={{ fontSize: 24, marginBottom: 6, textTransform: "none" }}>Daftarkan Perusahaan</h1>
          <p style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 22 }}>Satu akun admin untuk satu perusahaan.</p>
          {error && (
            <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 5, fontSize: 13, marginBottom: 16 }}>{error}</div>
          )}
          <form onSubmit={handleSubmit}>
            {field("organization_name", "Nama Perusahaan", "text", "PT Maju Konstruksi")}
            {field("full_name", "Nama Lengkap")}
            {field("email", "Email", "email", "anda@perusahaan.com")}
            {field("phone", "Telepon (opsional)", "tel")}
            {field("password", "Kata Sandi (min. 8 karakter)", "password")}
            <button className="btn-rust" type="submit" disabled={loading} style={{ width: "100%", justifyContent: "center", padding: "11px 0", marginTop: 8 }}>
              {loading ? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> : <UserPlus size={16} />} Daftar
            </button>
          </form>
        </div>
        <p style={{ textAlign: "center", fontSize: 13.5, color: "var(--steel)", marginTop: 20 }}>
          Sudah punya akun? <Link href="/login" style={{ color: "var(--rust)", fontWeight: 600 }}>Masuk</Link>
        </p>
      </div>
    </div>
  );
}
