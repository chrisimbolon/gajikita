"use client";
// =============================================================================
// /dashboard/shift — HR's Shifts page (G2b, 27 Oct 2026).
// Planned working hours. Lateness is measured against the shift start plus
// the grace minutes; a night shift (end before start) ends the next day.
// =============================================================================
import { Shift, hrApi, readErrors } from "@/lib/api/hr";
import { DAY_NAMES, hhmm } from "@/lib/format";
import { Loader2, Moon, Plus, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

interface Form { name: string; start_time: string; end_time: string; grace_minutes: number; working_days: string; is_active: boolean;
                 saturday_end_time: string | null }   // G17-5

const blank: Form = { name: "", start_time: "08:00", end_time: "17:00", grace_minutes: 10, working_days: "12345", is_active: true,
                      saturday_end_time: null };

export default function ShiftPage() {
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [editId, setEditId] = useState<string | null>(null);   // null = new
  const [form, setForm] = useState<Form>(blank);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try { setShifts(await hrApi.shifts()); setPageError(null); }
    catch (err) { setPageError(readErrors(err).summary); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const edit = (s: Shift | null) => {
    setEditId(s?.id ?? null);
    setForm(s ? { name: s.name, start_time: hhmm(s.start_time), end_time: hhmm(s.end_time), grace_minutes: s.grace_minutes,
                  working_days: s.working_days, is_active: s.is_active,
                  saturday_end_time: s.saturday_end_time ? hhmm(s.saturday_end_time) : null } : blank);
    setErrors({}); setMsg(null);
  };

  const toggleDay = (d: number) => {
    const k = String(d);
    const days = form.working_days.includes(k) ? form.working_days.replace(k, "") : form.working_days + k;
    setForm({ ...form, working_days: days.split("").sort().join("") });
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setErrors({}); setMsg(null);
    try {
      const shift = editId ? await hrApi.updateShift(editId, form) : await hrApi.createShift(form);
      await load();
      edit(shift);
      setMsg({ ok: true, text: "Tersimpan." });
    } catch (err) {
      const r = readErrors(err);
      setErrors(r.fields); setMsg({ ok: false, text: r.summary });
    } finally {
      setSaving(false);
    }
  };

  const night = form.end_time <= form.start_time;

  return (
    <div>
      <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Shift</h1>
      <p style={{ color: "var(--steel)", marginTop: 0, marginBottom: 18, fontSize: 14 }}>
        Jam kerja yang direncanakan. Terlambat dihitung dari jam mulai ditambah toleransi.
      </p>
      {pageError && <div className="card" style={{ color: "var(--danger)", marginBottom: 16 }}>{pageError}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 360px", gap: 18, alignItems: "start" }}>
        <div className="card" style={{ padding: 0 }}>
          {loading ? (
            <div style={{ padding: 24, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
          ) : shifts.length === 0 ? (
            <div style={{ padding: 24, color: "var(--steel)", fontSize: 14 }}>Belum ada shift. Buat yang pertama di sebelah kanan.</div>
          ) : (
            <table className="data-table">
              <thead><tr><th>Nama</th><th>Jam</th><th>Toleransi</th><th>Hari kerja</th></tr></thead>
              <tbody>
                {shifts.map((s) => (
                  <tr key={s.id} onClick={() => edit(s)} style={{ cursor: "pointer", opacity: s.is_active ? 1 : 0.55,
                                                                   background: editId === s.id ? "var(--paper)" : undefined }}>
                    <td style={{ fontWeight: 600 }}>{s.name}{!s.is_active ? " (nonaktif)" : ""}</td>
                    <td className="mono" style={{ fontSize: 13 }}>
                      {hhmm(s.start_time)}-{hhmm(s.end_time)}
                      {s.crosses_midnight && <Moon size={13} style={{ marginLeft: 6, verticalAlign: "-2px", color: "var(--steel)" }} />}
                      {s.saturday_end_time && <div style={{ fontSize: 11.5, color: "var(--steel)" }}>Sabtu s/d {hhmm(s.saturday_end_time)}</div>}
                    </td>
                    <td style={{ fontSize: 13 }}>{s.grace_minutes} menit</td>
                    <td style={{ fontSize: 13 }}>
                      {DAY_NAMES.map((d, i) => (s.working_days.includes(String(i + 1)) ? d : null)).filter(Boolean).join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <form onSubmit={save} className="card" style={{ padding: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={{ fontWeight: 700 }}>{editId ? "Ubah shift" : "Shift baru"}</div>
            {editId && (
              <button type="button" className="btn-ghost" onClick={() => edit(null)} style={{ padding: "4px 10px", fontSize: 12.5 }}>
                <Plus size={13} style={{ verticalAlign: "-2px" }} /> Baru
              </button>
            )}
          </div>
          <label className="label">Nama</label>
          <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Pagi" required />
          {errors.name && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 4 }}>{errors.name}</div>}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
            <div>
              <label className="label">Mulai</label>
              <input className="input" type="time" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} required />
            </div>
            <div>
              <label className="label">Selesai</label>
              <input className="input" type="time" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} required />
            </div>
          </div>
          {errors.end_time && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 4 }}>{errors.end_time}</div>}
          {night && form.end_time !== form.start_time && (
            <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 6 }}>
              <Moon size={13} style={{ verticalAlign: "-2px" }} /> Shift malam: selesai keesokan harinya.
            </div>
          )}

          {form.working_days.includes("6") && !night && (
            <>
              <label className="label" style={{ marginTop: 12 }}>Sabtu selesai jam (opsional)</label>
              <input className="input" type="time" value={form.saturday_end_time ?? ""}
                     onChange={(e) => setForm({ ...form, saturday_end_time: e.target.value || null })} />
              <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 4 }}>
                Kosongkan bila Sabtu sama dengan hari lain. Mis. kantor yang Sabtu hanya sampai 12:00.
              </div>
            </>
          )}

          <label className="label" style={{ marginTop: 12 }}>Toleransi terlambat (menit)</label>
          <input className="input" type="number" min={0} max={120} value={form.grace_minutes}
                 onChange={(e) => setForm({ ...form, grace_minutes: Number(e.target.value) || 0 })} />

          <label className="label" style={{ marginTop: 12 }}>Hari kerja</label>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {DAY_NAMES.map((d, i) => {
              const on = form.working_days.includes(String(i + 1));
              return (
                <button type="button" key={d} onClick={() => toggleDay(i + 1)} className="pill"
                        style={{ border: "1px solid var(--line)", cursor: "pointer",
                                 background: on ? "var(--workshop)" : "var(--paper-3)", color: on ? "#fff" : "var(--ink)" }}>
                  {d}
                </button>
              );
            })}
          </div>
          {errors.working_days && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 4 }}>{errors.working_days}</div>}

          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, marginTop: 14 }}>
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Aktif
          </label>

          {msg && <div style={{ marginTop: 10, fontSize: 13.5, fontWeight: 600, color: msg.ok ? "var(--workshop)" : "var(--danger)" }}>{msg.text}</div>}
          <button className="btn-rust" disabled={saving} style={{ width: "100%", justifyContent: "center", marginTop: 14 }}>
            {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={15} />} Simpan shift
          </button>
        </form>
      </div>
    </div>
  );
}
