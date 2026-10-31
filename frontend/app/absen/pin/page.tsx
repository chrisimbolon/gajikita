"use client";
// Change PIN: required on first login after HR sets one (G2a).
import { errorMessage, workerApi } from "@/lib/api/worker";
import { tokenStorage } from "@/lib/auth";
import { KeyRound, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

const digits = (v: string) => v.replace(/\D/g, "").slice(0, 6);
const pinStyle = { fontSize: 22, letterSpacing: "0.4em", padding: "12px 14px" };

export default function ChangePinPage() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tokenStorage.getAccess()) window.location.href = "/absen/masuk";
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (next !== again) { setError("PIN baru dan ulangan PIN tidak sama."); return; }
    setLoading(true);
    try {
      await workerApi.changePin(current, next);
      window.location.href = "/absen";
    } catch (err) {
      setError(errorMessage(err, "PIN belum bisa diganti. Periksa sinyal lalu coba lagi."));
      setLoading(false);
    }
  };

  return (
    <div style={{ paddingTop: 40 }}>
      <div className="card">
        <h1 className="display" style={{ fontSize: 24, marginBottom: 6, textTransform: "none" }}>Buat PIN Baru</h1>
        <p style={{ fontSize: 14, color: "var(--steel)", marginBottom: 22 }}>
          Ganti PIN dari HR dengan PIN pilihan Anda. Jangan pakai angka sama atau berurutan (mis. 111111, 123456).
        </p>
        {error && (
          <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "10px 14px", borderRadius: 5,
                        fontSize: 14, marginBottom: 16 }}>{error}</div>
        )}
        <form onSubmit={submit}>
          {([["cur", "PIN dari HR", current, setCurrent], ["new", "PIN baru", next, setNext],
             ["again", "Ulangi PIN baru", again, setAgain]] as const).map(([id, label, value, set]) => (
            <div key={id} style={{ marginBottom: 16 }}>
              <label className="label" htmlFor={id}>{label}</label>
              <input id={id} className="input mono" type="password" inputMode="numeric" maxLength={6} required
                     value={value} onChange={(e) => set(digits(e.target.value))} placeholder="••••••" style={pinStyle} />
            </div>
          ))}
          <button className="btn-rust" type="submit"
                  disabled={loading || current.length !== 6 || next.length !== 6 || again.length !== 6}
                  style={{ width: "100%", justifyContent: "center", padding: "14px 0", fontSize: 16, marginTop: 6 }}>
            {loading ? <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> : <KeyRound size={18} />} Simpan PIN
          </button>
        </form>
      </div>
    </div>
  );
}
