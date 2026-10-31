"use client";
// Worker login: phone number + 6-digit PIN (G2a).
import Wordmark from "@/components/Wordmark";
import { errorMessage, workerApi } from "@/lib/api/worker";
import { Loader2, LogIn } from "lucide-react";
import { useState } from "react";

export default function WorkerLoginPage() {
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { must_change_pin } = await workerApi.login(phone, pin);
      // Full page load on purpose, so the app starts fresh with the new login.
      window.location.href = must_change_pin ? "/absen/pin" : "/absen";
    } catch (err) {
      setError(errorMessage(err, "Tidak bisa masuk. Periksa sinyal lalu coba lagi."));
      setPin("");
      setLoading(false);
    }
  };

  return (
    <div style={{ paddingTop: 40 }}>
      <div style={{ display: "flex", justifyContent: "center", marginBottom: 24 }}><Wordmark size={28} /></div>
      <div className="card">
        <h1 className="display" style={{ fontSize: 26, marginBottom: 6, textTransform: "none" }}>Absen Karyawan</h1>
        <p style={{ fontSize: 14, color: "var(--steel)", marginBottom: 22 }}>Masuk dengan No. HP dan PIN dari HR.</p>
        {error && (
          <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 5,
                        fontSize: 14, marginBottom: 16 }}>{error}</div>
        )}
        <form onSubmit={submit}>
          <div style={{ marginBottom: 16 }}>
            <label className="label" htmlFor="phone">No. HP</label>
            <input id="phone" className="input" type="tel" inputMode="tel" autoComplete="tel" required
                   value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="0812 3456 7890"
                   style={{ fontSize: 18, padding: "12px 14px" }} />
          </div>
          <div style={{ marginBottom: 22 }}>
            <label className="label" htmlFor="pin">PIN (6 angka)</label>
            <input id="pin" className="input mono" type="password" inputMode="numeric" autoComplete="current-password"
                   pattern="[0-9]{6}" maxLength={6} required value={pin}
                   onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="••••••"
                   style={{ fontSize: 22, letterSpacing: "0.4em", padding: "12px 14px" }} />
          </div>
          <button className="btn-rust" type="submit" disabled={loading || pin.length !== 6}
                  style={{ width: "100%", justifyContent: "center", padding: "14px 0", fontSize: 16 }}>
            {loading ? <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> : <LogIn size={18} />} Masuk
          </button>
        </form>
      </div>
      <p style={{ textAlign: "center", fontSize: 13, color: "var(--steel)", marginTop: 18 }}>
        Lupa PIN? Minta HR mengatur ulang.
      </p>
    </div>
  );
}
