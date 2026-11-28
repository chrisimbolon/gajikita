"use client";
// =============================================================================
// /dashboard/pengguna — the company's office users (G22-1, 28 Nov 2026). Owner or admin only.
// Add an HR user (SeeGaji gives a temporary password, shown once, changed at first login), switch someone off,
// reset a forgotten password, change a role. Every change is in the audit log.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { Member, MemberAction, MemberList, MemberRole, ROLE_LABELS, usersApi } from "@/lib/api/users";
import { Copy, KeyRound, Loader2, Power, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";

const DATE = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

function TempPassword({ who, password, onClose }: { who: string; password: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="card" style={{ marginBottom: 14, background: "#FFF4E5", borderColor: "#F0C987" }}>
      <div style={{ fontWeight: 800, color: "#5C3D00", marginBottom: 6 }}>Password sementara untuk {who}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 22, fontWeight: 700, letterSpacing: "0.06em", color: "var(--midnight)" }}>{password}</span>
        <button className="btn-ghost" onClick={() => { navigator.clipboard?.writeText(password); setCopied(true); }}
                style={{ padding: "5px 10px", fontSize: 12.5 }}>
          <Copy size={13} /> {copied ? "Tersalin" : "Salin"}
        </button>
      </div>
      <div style={{ fontSize: 13, color: "#5C3D00", marginTop: 8 }}>
        Hanya ditampilkan sekali. Sampaikan langsung atau lewat telepon, sebaiknya jangan lewat chat. Saat login pertama,
        {" "}{who} wajib membuat password sendiri.
      </div>
      <button className="btn-ghost" onClick={onClose} style={{ marginTop: 10, padding: "5px 10px", fontSize: 12.5 }}>
        Sudah saya catat
      </button>
    </div>
  );
}

export default function UsersPage() {
  const [data, setData] = useState<MemberList | null>(null);
  const [denied, setDenied] = useState("");
  const [form, setForm] = useState<{ email: string; full_name: string; phone: string; role: MemberRole }>(
    { email: "", full_name: "", phone: "", role: "hr" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [shown, setShown] = useState<{ who: string; password: string } | null>(null);

  const load = () => usersApi.list().then(setData).catch((err) => setDenied(readErrors(err).summary || "Tidak bisa dibuka."));
  useEffect(() => { load(); }, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("add");
    setError("");
    try {
      const res = await usersApi.add({ ...form, email: form.email.trim(), full_name: form.full_name.trim() });
      setShown({ who: res.member.user.full_name, password: res.temp_password });
      setForm({ email: "", full_name: "", phone: "", role: "hr" });
      await load();
    } catch (err) {
      setError(readErrors(err).summary || "Gagal menambah pengguna.");
    } finally {
      setBusy(null);
    }
  };

  const act = async (m: Member, action: MemberAction, role?: MemberRole) => {
    const ask = { deactivate: `Nonaktifkan ${m.user.full_name}? Ia langsung keluar dari semua perangkat dan tidak bisa login.`,
                  reset_password: `Reset password ${m.user.full_name}? Password lamanya langsung tidak berlaku.`,
                  activate: "", set_role: "" }[action];
    if (ask && !window.confirm(ask)) return;
    setBusy(m.id + action);
    setError("");
    try {
      const res = await usersApi.act(m.id, action, role);
      if (res.temp_password) setShown({ who: m.user.full_name, password: res.temp_password });
      await load();
    } catch (err) {
      setError(readErrors(err).summary || "Gagal menyimpan.");
    } finally {
      setBusy(null);
    }
  };

  if (denied) return <div className="card">{denied}</div>;
  if (!data) return <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />;
  const canTouch = (m: Member) => !m.is_me && data.can_assign.includes(m.role);

  return (
    <div>
      <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Pengguna</h1>
      <div style={{ color: "var(--steel)", marginBottom: 18 }}>
        Siapa saja yang boleh membuka SeeGaji di kantor. Setiap orang punya login sendiri, jadi riwayat perubahan
        menunjukkan siapa melakukan apa.
      </div>

      {shown && <TempPassword who={shown.who} password={shown.password} onClose={() => setShown(null)} />}
      {error && <div className="card" style={{ marginBottom: 14, color: "var(--danger)" }}>{error}</div>}

      <form className="card" onSubmit={add} style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 16, fontWeight: 800, color: "var(--midnight)", display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <UserPlus size={17} /> Tambah pengguna
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
          <label><div className="label">Nama</div>
            <input className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} style={{ width: "100%" }} /></label>
          <label><div className="label">Email (untuk login)</div>
            <input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} style={{ width: "100%" }} /></label>
          <label><div className="label">No. HP (boleh kosong)</div>
            <input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} style={{ width: "100%" }} /></label>
          <label><div className="label">Peran</div>
            <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as MemberRole })} style={{ width: "100%" }}>
              {data.can_assign.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select></label>
        </div>
        <div style={{ fontSize: 12.5, color: "var(--steel)", margin: "8px 0 10px" }}>
          HR: semua halaman kantor. Admin: sama dengan HR, ditambah mengatur pengguna HR.
        </div>
        <button className="btn-rust" disabled={busy === "add" || !form.email || !form.full_name}>
          {busy === "add" ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Tambah & buat password sementara"}
        </button>
      </form>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table" style={{ width: "100%" }}>
          <thead><tr><th>Nama</th><th>Peran</th><th>Status</th><th>Login terakhir</th><th /></tr></thead>
          <tbody>
            {data.members.map((m) => (
              <tr key={m.id} style={{ opacity: m.is_active ? 1 : 0.55 }}>
                <td>
                  <div style={{ fontWeight: 700 }}>{m.user.full_name}{m.is_me ? " (saya)" : ""}</div>
                  <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{m.user.email}</div>
                </td>
                <td>
                  {canTouch(m) && m.is_active && data.can_assign.length > 1 ? (
                    <select className="input" value={m.role} disabled={!!busy}
                            onChange={(e) => act(m, "set_role", e.target.value as MemberRole)} style={{ padding: "4px 8px" }}>
                      {data.can_assign.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                    </select>
                  ) : m.role_label}
                </td>
                <td>
                  {!m.is_active ? <span className="pill">Nonaktif</span>
                    : m.user.must_change_password ? <span className="pill" style={{ background: "#FFF4E5", color: "#8A5A00" }}>Belum ganti password</span>
                    : <span className="pill" style={{ background: "#E7F4EC", color: "#1F7A4D" }}>Aktif</span>}
                </td>
                <td style={{ fontSize: 13, color: "var(--steel)" }}>{m.user.last_login ? DATE.format(new Date(m.user.last_login)) : "Belum pernah"}</td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  {canTouch(m) && (m.is_active ? (
                    <>
                      <button className="btn-ghost" disabled={!!busy} onClick={() => act(m, "reset_password")}
                              style={{ padding: "5px 9px", fontSize: 12.5, marginRight: 6 }}><KeyRound size={13} /> Reset password</button>
                      <button className="btn-ghost" disabled={!!busy} onClick={() => act(m, "deactivate")}
                              style={{ padding: "5px 9px", fontSize: 12.5, color: "var(--danger)" }}><Power size={13} /> Nonaktifkan</button>
                    </>
                  ) : (
                    <button className="btn-ghost" disabled={!!busy} onClick={() => act(m, "activate")}
                            style={{ padding: "5px 9px", fontSize: 12.5 }}><Power size={13} /> Aktifkan lagi</button>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
