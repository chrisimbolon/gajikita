"use client";
// =============================================================================
// /dashboard/absensi/kejadian — company events ("Kejadian", G17-2, 14 Nov 2026).
// A power cut or a holiday, entered ONCE for a date range and a group of people, instead of deciding
// every person's day in Perlu Tinjau (DKCB, 12-14 Okt 2026: "Mati lampu").
// =============================================================================
import { CompanyEvent, EventInput, EventKind, eventApi } from "@/lib/api/events";
import { Employee, Site, hrApi, readErrors } from "@/lib/api/hr";
import { todayISO } from "@/lib/format";
import { CalendarX2, Loader2, Plus, Save, Trash2, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const day = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
};
const range = (e: { start: string; end: string }) => (e.start === e.end ? day(e.start) : `${day(e.start)} – ${day(e.end)}`);

const KINDS: { key: EventKind; label: string; help: string }[] = [
  { key: "gangguan", label: "Gangguan absen",
    help: "Mati lampu, mesin rusak. Tap yang hilang dimaafkan: tidak ada potongan ½ hari atau tidak hadir. Yang tercatat tetap dihitung: terlambat, pulang cepat, dan lembur dari tap." },
  { key: "libur", label: "Libur",
    help: "Libur perusahaan atau libur nasional. Hari kerja jadi hari libur: tidak ada yang tidak hadir, yang tetap masuk dibayar tarif hari libur." },
];

const blank = (): EventInput => ({ start: todayISO(), end: todayISO(), kind: "gangguan", reason: "", everyone: true,
                                    site_ids: [], employee_ids: [] });

export default function KejadianPage() {
  const [events, setEvents] = useState<CompanyEvent[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [people, setPeople] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<EventInput>(blank);
  const [search, setSearch] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [ev, st, em] = await Promise.all([eventApi.list(), hrApi.sites(), hrApi.employees()]);
      setEvents(ev); setSites(st.filter((s) => s.is_active)); setPeople(em); setPageError(null);
    } catch (err) {
      setPageError(readErrors(err).summary);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const edit = (e: CompanyEvent | null) => {
    setEditId(e?.id ?? null);
    setForm(e ? { start: e.start, end: e.end, kind: e.kind, reason: e.reason, everyone: e.everyone,
                  site_ids: e.sites.map((s) => s.id), employee_ids: e.employees.map((p) => p.id) } : blank());
    setMsg(null); setSearch("");
  };

  const toggle = (key: "site_ids" | "employee_ids", id: string) => {
    const list = form[key];
    setForm({ ...form, [key]: list.includes(id) ? list.filter((x) => x !== id) : [...list, id] });
  };

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = q ? people.filter((p) => `${p.full_name} ${p.employee_no}`.toLowerCase().includes(q)) : people;
    return list.slice(0, 60);
  }, [people, search]);

  const save = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const res = editId ? await eventApi.update(editId, form) : await eventApi.create(form);
      setEvents(res.events);
      edit(res.event);
      setMsg({ ok: true, text: "Tersimpan. Hitung ulang payroll periode itu supaya angkanya ikut berubah." });
    } catch (err) {
      setMsg({ ok: false, text: readErrors(err).summary });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!editId) return;
    setBusy(true); setMsg(null);
    try {
      setEvents(await eventApi.remove(editId));
      edit(null);
      setMsg({ ok: true, text: "Kejadian dihapus. Hitung ulang payroll periode itu." });
    } catch (err) {
      setMsg({ ok: false, text: readErrors(err).summary });
    } finally {
      setBusy(false);
    }
  };

  const kind = KINDS.find((k) => k.key === form.kind)!;

  return (
    <div>
      <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Kejadian</h1>
      <p style={{ color: "var(--steel)", marginTop: 0, marginBottom: 18, fontSize: 14, maxWidth: 760 }}>
        Mati lampu, mesin rusak, atau libur: cukup dicatat sekali untuk beberapa hari dan sekelompok karyawan.
        Hari-hari itu tidak perlu ditinjau satu per satu lagi.
      </p>
      {pageError && <div className="card" style={{ color: "var(--danger)", marginBottom: 16 }}>{pageError}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 400px", gap: 18, alignItems: "start" }}>
        <div className="card" style={{ padding: 0 }}>
          {loading ? (
            <div style={{ padding: 24, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
          ) : events.length === 0 ? (
            <div style={{ padding: 24, color: "var(--steel)", fontSize: 14 }}>
              Belum ada kejadian. Contoh: <b>Gangguan absen</b>, 12–14 Okt, &quot;Mati lampu&quot;, semua karyawan.
            </div>
          ) : (
            <table className="data-table">
              <thead><tr><th>Tanggal</th><th>Jenis</th><th>Alasan</th><th>Berlaku untuk</th></tr></thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} onClick={() => edit(e)} style={{ cursor: "pointer", background: editId === e.id ? "var(--paper)" : undefined }}>
                    <td style={{ fontSize: 13.5, whiteSpace: "nowrap" }}>
                      {range(e)}
                      <div style={{ fontSize: 12, color: "var(--steel)" }}>{e.days} hari</div>
                    </td>
                    <td>
                      <span className="pill" style={{ background: e.kind === "libur" ? "var(--paper-3)" : "var(--hazard-light)",
                                                      fontSize: 12, fontWeight: 700 }}>
                        {e.kind === "libur" ? <CalendarX2 size={12} style={{ verticalAlign: "-2px" }} /> : <Zap size={12} style={{ verticalAlign: "-2px" }} />}{" "}
                        {e.kind_label}
                      </span>
                    </td>
                    <td style={{ fontWeight: 600 }}>{e.reason}</td>
                    <td style={{ fontSize: 13 }}>{e.who}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <form onSubmit={save} className="card" style={{ padding: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={{ fontWeight: 700 }}>{editId ? "Ubah kejadian" : "Kejadian baru"}</div>
            {editId && (
              <button type="button" className="btn-ghost" onClick={() => edit(null)} style={{ padding: "4px 10px", fontSize: 12.5 }}>
                <Plus size={13} style={{ verticalAlign: "-2px" }} /> Baru
              </button>
            )}
          </div>

          <label className="label">Jenis</label>
          <div style={{ display: "flex", gap: 6 }}>
            {KINDS.map((k) => (
              <button type="button" key={k.key} onClick={() => setForm({ ...form, kind: k.key })} className="pill"
                      style={{ border: "1px solid var(--line)", cursor: "pointer", flex: 1, justifyContent: "center",
                               background: form.kind === k.key ? "var(--midnight)" : "var(--paper-3)",
                               color: form.kind === k.key ? "#fff" : "var(--ink)" }}>
                {k.label}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 6 }}>{kind.help}</div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
            <div>
              <label className="label">Mulai</label>
              <input className="input" type="date" value={form.start} required
                     onChange={(e) => setForm({ ...form, start: e.target.value, end: form.end < e.target.value ? e.target.value : form.end })} />
            </div>
            <div>
              <label className="label">Sampai</label>
              <input className="input" type="date" value={form.end} min={form.start} required
                     onChange={(e) => setForm({ ...form, end: e.target.value })} />
            </div>
          </div>

          <label className="label" style={{ marginTop: 12 }}>Alasan</label>
          <input className="input" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })}
                 placeholder={form.kind === "libur" ? "mis. HUT perusahaan" : "mis. Mati lampu"} required />

          <label className="label" style={{ marginTop: 12 }}>Berlaku untuk</label>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 14 }}>
            <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="radio" checked={form.everyone} onChange={() => setForm({ ...form, everyone: true })} /> Semua karyawan
            </label>
            <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="radio" checked={!form.everyone} onChange={() => setForm({ ...form, everyone: false })} />
              Lokasi dan/atau karyawan tertentu
            </label>
          </div>

          {!form.everyone && (
            <div style={{ marginTop: 10, padding: 12, border: "1px solid var(--line)", borderRadius: 10 }}>
              <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 6 }}>Lokasi (lokasi utama karyawan)</div>
              {sites.length === 0 ? (
                <div style={{ fontSize: 12.5, color: "var(--steel)" }}>Belum ada lokasi.</div>
              ) : (
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {sites.map((s) => {
                    const on = form.site_ids.includes(s.id);
                    return (
                      <button type="button" key={s.id} onClick={() => toggle("site_ids", s.id)} className="pill"
                              style={{ border: "1px solid var(--line)", cursor: "pointer",
                                       background: on ? "var(--workshop)" : "var(--paper-3)", color: on ? "#fff" : "var(--ink)" }}>
                        {s.name}
                      </button>
                    );
                  })}
                </div>
              )}

              <div style={{ fontSize: 12.5, fontWeight: 700, margin: "12px 0 6px" }}>
                Karyawan {form.employee_ids.length > 0 && <span style={{ color: "var(--steel)" }}>({form.employee_ids.length} dipilih)</span>}
              </div>
              <input className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama atau no. karyawan" />
              <div style={{ maxHeight: 220, overflowY: "auto", marginTop: 6 }}>
                {shown.map((p) => (
                  <label key={p.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13.5, padding: "4px 2px" }}>
                    <input type="checkbox" checked={form.employee_ids.includes(p.id)} onChange={() => toggle("employee_ids", p.id)} />
                    <span>{p.full_name} <span style={{ color: "var(--steel)", fontSize: 12 }}>{p.employee_no}</span></span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {msg && <div style={{ marginTop: 10, fontSize: 13.5, fontWeight: 600, color: msg.ok ? "var(--workshop)" : "var(--danger)" }}>{msg.text}</div>}
          <button className="btn-rust" disabled={busy} style={{ width: "100%", justifyContent: "center", marginTop: 14 }}>
            {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={15} />} Simpan kejadian
          </button>
          {editId && (
            <button type="button" className="btn-ghost" disabled={busy} onClick={remove}
                    style={{ width: "100%", justifyContent: "center", marginTop: 8, color: "var(--danger)" }}>
              <Trash2 size={14} /> Hapus kejadian
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
