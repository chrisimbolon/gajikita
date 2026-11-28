"use client";
// =============================================================================
// /dashboard/akun — "Akun saya" (G22-1, 28 Nov 2026): who I am, and "Ubah password".
// A temporary password (a new user, or one reset by the owner) is changed here first;
// the layout keeps every other page closed until then. Changing it signs out every other device.
// =============================================================================
import { useAuth } from "@/context/AuthContext";
import { authApi } from "@/lib/api/auth";
import { CheckCircle2, KeyRound, Loader2, ShieldAlert } from "lucide-react";
import { useState } from "react";

function fieldErrors(err: unknown): Record<string, string> {
  const e = err as { response?: { data?: { errors?: Record<string, string[]>; detail?: string } } };
  if (!e?.response) return { _: "Tidak bisa terhubung ke server. Periksa koneksi lalu coba lagi." };
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(e.response.data?.errors ?? {})) out[k] = (Array.isArray(v) ? v : [String(v)]).join(" ");
  if (!Object.keys(out).length) out._ = e.response.data?.detail ?? "Gagal menyimpan. Coba lagi.";
  return out;
}

export default function AccountPage() {
  const { user, organization, orgRole, updateUser } = useAuth();
  const [form, setForm] = useState({ old: "", next: "", again: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const mustChange = !!user?.must_change_password;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setDone(false);
    if (form.next !== form.again) { setErrors({ again: "Ketik password baru yang sama dua kali." }); return; }
    setSaving(true);
    setErrors({});
    try {
      updateUser(await authApi.changePassword(form.old, form.next));
      setForm({ old: "", next: "", again: "" });
      setDone(true);
    } catch (err) {
      setErrors(fieldErrors(err));
    } finally {
      setSaving(false);
    }
  };

  const input = (key: "old" | "next" | "again", label: string, error?: string) => (
    <label style={{ display: "block", marginBottom: 12 }}>
      <div className="label">{label}</div>
      <input className="input" type="password" autoComplete={key === "old" ? "current-password" : "new-password"}
             value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} style={{ width: "100%" }} />
      {error && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 4 }}>{error}</div>}
    </label>
  );

  return (
    <div style={{ maxWidth: 560 }}>
      <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Akun saya</h1>
      <div style={{ color: "var(--steel)", marginBottom: 18 }}>
        {user?.full_name} · {user?.email}{organization ? ` · ${organization.name}` : ""}
        {orgRole ? ` · ${orgRole === "owner" ? "Pemilik" : orgRole === "admin" ? "Admin" : "HR"}` : ""}
      </div>

      {mustChange && (
        <div className="card" style={{ marginBottom: 14, background: "#FFF4E5", borderColor: "#F0C987", display: "flex", gap: 10 }}>
          <ShieldAlert size={18} style={{ color: "#8A5A00", flexShrink: 0, marginTop: 2 }} />
          <div style={{ fontSize: 14, color: "#5C3D00" }}>
            <b>Ganti password sementara dulu.</b> Password ini diberikan orang lain, jadi buat password sendiri sebelum
            memakai SeeGaji. Password lama = password sementara yang Anda terima.
          </div>
        </div>
      )}

      <form className="card" onSubmit={save}>
        <div style={{ fontSize: 16, fontWeight: 800, color: "var(--midnight)", display: "flex", alignItems: "center", gap: 8 }}>
          <KeyRound size={17} /> Ubah password
        </div>
        <div style={{ fontSize: 13, color: "var(--steel)", margin: "2px 0 14px" }}>
          Minimal 8 karakter, jangan sama dengan email atau nama. Setelah diganti, semua perangkat lain otomatis keluar.
        </div>
        {input("old", mustChange ? "Password sementara" : "Password lama", errors.old_password)}
        {input("next", "Password baru", errors.new_password)}
        {input("again", "Ulangi password baru", errors.again)}
        {errors._ && <div style={{ color: "var(--danger)", fontSize: 13, marginBottom: 10 }}>{errors._}</div>}
        {done && (
          <div style={{ color: "var(--success, #1F7A4D)", fontSize: 13.5, fontWeight: 600, marginBottom: 10, display: "flex", gap: 6 }}>
            <CheckCircle2 size={16} /> Password diganti. Perangkat lain sudah dikeluarkan.
          </div>
        )}
        <button className="btn-rust" disabled={saving || !form.old || !form.next || !form.again}
                style={{ width: "100%", justifyContent: "center" }}>
          {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan password baru"}
        </button>
      </form>
    </div>
  );
}
