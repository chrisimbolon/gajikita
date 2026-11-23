"use client";
// =============================================================================
// /dashboard/lembur/spl — SPL (Surat Perintah Lembur), G17-E1 (23 Nov 2026).
// HR records the paper SPL once for several people; the taps give the hours. In "SPL" mode (Payroll → Pengaturan)
// a day HR hasn't decided is paid when an SPL covers it; "Lembur tanpa SPL" is listed and not paid.
// HR's own decision on a day always wins. Locked payrolls never change.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { todayISO } from "@/lib/format";
import { SplInput, SplLogRow, SplOrder, SplPage, splApi } from "@/lib/api/spl";
import { ArrowLeft, FilePlus2, Info, Loader2, Paperclip, Search, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";

const MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"];
const MON = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const dateText = (iso: string) => `${Number(iso.slice(8, 10))} ${MON[Number(iso.slice(5, 7)) - 1]}`;
const span = (a: string, b: string) => (a === b ? dateText(a) : `${dateText(a)} – ${dateText(b)}`);
const hours = (m: number) => { const h = Math.floor(m / 60), r = m % 60; return r ? `${h} j ${r} m` : `${h} jam`; };
const clock = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }) : "-");
const hint: CSSProperties = { fontSize: 12.5, color: "var(--steel)", marginTop: 3 };
const STATE: Record<string, { text: string; color: string }> = {
  spl: { text: "dibayar (SPL)", color: "#2E7D4F" },
  decided: { text: "keputusan HR", color: "var(--midnight)" },
  waiting: { text: "menunggu HR", color: "#9A6700" },
  none: { text: "tidak ada lembur di finger", color: "var(--steel)" },
};

function blank(date: string): SplInput {
  return { start_date: date, end_date: date, work: "", site: null, planned_start: null, planned_end: null,
           issued_by_name: "", employee_ids: [], consent: "yes", note: "", attachment: null };
}

export default function SplPageView() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [data, setData] = useState<SplPage | null>(null);
  const [editing, setEditing] = useState<{ id: string | null; form: SplInput } | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async (m?: string) => {
    try { setData(await splApi.page(m)); }
    catch (e) { setMessage({ ok: false, text: readErrors(e).summary }); }
  }, []);
  useEffect(() => { load(month); }, [month, load]);

  const ym = data ? `${data.period.year}-${String(data.period.month).padStart(2, "0")}` : undefined;
  const shift = (step: number) => {
    if (!data) return;
    const k = data.period.year * 12 + data.period.month - 1 + step;
    setMonth(`${Math.floor(k / 12)}-${String((k % 12) + 1).padStart(2, "0")}`);
  };
  const done = (page: SplPage) => { setData(page); setEditing(null); setMessage({ ok: true, text: page.message ?? "Disimpan." }); };

  const cancel = async (o: SplOrder) => {
    const note = window.prompt(`Batalkan SPL ${o.number}? Tulis alasannya (boleh kosong):`, "");
    if (note === null) return;
    try { done(await splApi.cancel(o.id, note, ym)); }
    catch (e) { setMessage({ ok: false, text: readErrors(e).summary }); }
  };
  const openPhoto = async (o: SplOrder) => {
    try { window.open(URL.createObjectURL(await splApi.photo(o.id)), "_blank"); }
    catch (e) { setMessage({ ok: false, text: readErrors(e).summary }); }
  };
  const edit = (o: SplOrder) => setEditing({ id: o.id, form: {
    start_date: o.start_date, end_date: o.end_date, work: o.work, site: o.site?.id ?? null,
    planned_start: o.planned_start, planned_end: o.planned_end, issued_by_name: o.issued_by_name,
    employee_ids: o.people.map((p) => p.employee.id), consent: o.people.every((p) => p.consent === "yes") ? "yes" : "pending",
    note: o.note, attachment: null } });

  if (!data) {
    return <div style={{ padding: 30, color: "var(--steel)" }}>
      {message ? message.text : <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />}
    </div>;
  }
  const active = data.orders.filter((o) => o.status === "active");
  const cancelled = data.orders.filter((o) => o.status !== "active");

  return (
    <div>
      <Link href="/dashboard/lembur" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 14, color: "var(--steel)" }}>
        <ArrowLeft size={15} /> Lembur
      </Link>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap", marginTop: 6 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>SPL (Surat Perintah Lembur)</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14, maxWidth: 760 }}>
            Catat SPL sekali untuk beberapa orang. Jam lembur tetap diambil dari finger (pembulatan dan aturan jam 18:00).
            UU No. 27/2026 Pasal 116 ayat 1: lembur perlu persetujuan karyawan dan perintah tertulis atau digital.
          </p>
          <p style={{ margin: "6px 0 0", fontSize: 13.5, color: data.mode === "spl" ? "#2E7D4F" : "#2563A8" }}>
            <Info size={13} style={{ verticalAlign: "-2px" }} />{" "}
            {data.mode === "spl"
              ? "Mode SPL: lembur dibayar otomatis bila ada SPL; lembur tanpa SPL tidak dibayar. Keputusan HR per hari tetap menang."
              : "Mode keputusan HR: lembur tetap diputuskan HR per hari (Lembur / file rekap). SPL di sini sebagai catatan."}{" "}
            <Link href="/dashboard/payroll/pengaturan" style={{ color: "var(--rust)" }}>Ubah di Pengaturan payroll</Link>
          </p>
        </div>
        <button className="btn-rust" onClick={() => setEditing({ id: null, form: blank(data.period.end > todayISO() ? todayISO() : data.period.end) })}
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <FilePlus2 size={16} /> Catat SPL
        </button>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "14px 0" }}>
        <button className="btn-ghost" onClick={() => shift(-1)}>‹</button>
        <div style={{ fontWeight: 700 }}>Periode gaji {MONTHS[data.period.month - 1]} {data.period.year}: {span(data.period.start, data.period.end)}</div>
        <button className="btn-ghost" onClick={() => shift(1)}>›</button>
      </div>

      {message && (
        <div style={{ padding: "10px 14px", borderRadius: 6, marginBottom: 14, fontSize: 14,
                      background: message.ok ? "#E8F3EC" : "#FBEAEA", color: message.ok ? "#2E7D4F" : "var(--danger)" }}>
          {message.text}
        </div>
      )}

      {/* G17-E1.1: always shown, also when empty */}
      {(
        <div className="card" style={{ marginBottom: 14 }}>
          <div style={{ fontWeight: 800, color: "var(--midnight)" }}>Lembur tanpa SPL ({data.unmatched.length} hari)</div>
          <div style={hint}>
            {data.mode === "spl" ? "Tidak dibayar sampai ada SPL atau HR memutuskan di Lembur." : "Belum ada SPL; HR masih memutuskan per hari."}
            {" "}Klik &quot;Buat SPL&quot; bila lembur itu memang diperintahkan.
          </div>
          {data.unmatched.length === 0 ? (
            <div style={{ marginTop: 8, fontSize: 14, color: "var(--steel)" }}>
              Tidak ada lembur tanpa SPL di periode ini (lembur yang sudah diputuskan HR atau dari file rekap tidak masuk sini).
            </div>
          ) : (
          <table className="data-table" style={{ marginTop: 8 }}>
            <thead><tr><th>Karyawan</th><th>Tanggal</th><th>Masuk–pulang</th><th>Lembur di finger</th><th /></tr></thead>
            <tbody>
              {data.unmatched.map((u) => (
                <tr key={u.day_id}>
                  <td>{u.employee.full_name}</td><td>{dateText(u.date)}</td>
                  <td>{clock(u.in)}–{clock(u.out)}</td><td>{hours(u.minutes)}</td>
                  <td><button className="btn-ghost" onClick={() => setEditing({ id: null, form: { ...blank(u.date), employee_ids: [u.employee.id] } })}>Buat SPL</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          )}
        </div>
      )}

      <div className="card" style={{ padding: 0 }}>
        {active.length === 0 ? (
          <div style={{ padding: 24, color: "var(--steel)", fontSize: 14 }}>Belum ada SPL di periode ini.</div>
        ) : (
          <table className="data-table">
            <thead><tr><th>No.</th><th>Tanggal</th><th>Pekerjaan</th><th>Rencana</th><th>Karyawan dan lembur</th><th /></tr></thead>
            <tbody>
              {active.map((o) => (
                <tr key={o.id}>
                  <td className="mono">{o.number}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{span(o.start_date, o.end_date)}</td>
                  <td>{o.work}{o.site && <div style={hint}>{o.site.name}</div>}
                    {o.issued_by_name && <div style={hint}>Dari: {o.issued_by_name}</div>}
                    {o.has_attachment && <button className="btn-ghost" style={{ marginTop: 4 }} onClick={() => openPhoto(o)}><Paperclip size={13} /> Foto SPL</button>}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{o.planned_start ? `${o.planned_start}–${o.planned_end}` : "-"}</td>
                  <td>
                    {o.people.map((p) => (
                      <div key={p.employee.id} style={{ marginBottom: 4 }}>
                        <b>{p.employee.full_name}</b>
                        {p.consent !== "yes" && <span style={{ color: "#2563A8", fontSize: 12.5 }}> · persetujuan belum tercatat</span>}
                        <div style={{ fontSize: 12.5 }}>
                          {p.days.length === 0 ? <span style={{ color: "var(--steel)" }}>belum ada absen</span>
                            : p.days.map((d) => (
                              <span key={d.date} style={{ marginRight: 10, color: STATE[d.state].color }}>
                                {dateText(d.date)}: {d.paid ? hours(d.paid) : ""} {STATE[d.state].text}
                                {d.over_plan > 0 && <span style={{ color: "#2563A8" }}> (lewat rencana {hours(d.over_plan)})</span>}
                              </span>
                            ))}
                        </div>
                      </div>
                    ))}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="btn-ghost" onClick={() => edit(o)}>Ubah</button>{" "}
                    <button className="btn-ghost" onClick={() => cancel(o)}>Batalkan</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data.summary && <SplLog data={data} />}
      {cancelled.length > 0 && (
        <div style={{ ...hint, marginTop: 10 }}>
          Dibatalkan: {cancelled.map((o) => `SPL ${o.number} (${span(o.start_date, o.end_date)}${o.cancel_note ? `: ${o.cancel_note}` : ""})`).join(" · ")}
        </div>
      )}

      {editing && (
        <SplDialog data={data} id={editing.id} initial={editing.form} month={ym}
                   onClose={() => setEditing(null)} onDone={done} />
      )}
    </div>
  );
}

// G17-E3: who orders overtime, for what, how long; and UU 27/2026 Pasal 116 ayat 1 huruf c
function csvCell(v: string | number) {
  const s = String(v);
  return /[",;\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function SplLog({ data }: { data: SplPage }) {
  const s = data.summary!;
  const name = `${MONTHS[data.period.month - 1]} ${data.period.year}`;
  const download = () => {
    const rows: (string | number)[][] = [
      [`Rekap lembur periode gaji ${name} (${data.period.start} s/d ${data.period.end})`],
      [],
      ["Per atasan", "SPL", "Orang-hari", "Jam"],
      ...s.by_issuer.map((r) => [r.name, r.orders, r.person_days, (r.minutes / 60).toFixed(2)]),
      [],
      ["Per pekerjaan", "SPL", "Orang-hari", "Jam"],
      ...s.by_work.map((r) => [r.name, r.orders, r.person_days, (r.minutes / 60).toFixed(2)]),
      [],
      ["Karyawan", "No.", "Hari lembur", "Jam", "Hari > 4 jam", "Minggu > 18 jam"],
      ...s.by_person.map((p) => [p.employee.full_name, p.employee.employee_no, p.days, (p.minutes / 60).toFixed(2),
                                 p.long_days.length, p.heavy_weeks.length]),
    ];
    const blob = new Blob(["\ufeff" + rows.map((r) => r.map(csvCell).join(",")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `rekap-lembur-${data.period.year}-${String(data.period.month).padStart(2, "0")}.csv`;
    a.click();
  };
  const table = (title: string, rows: SplLogRow[]) => (
    <div style={{ flex: "1 1 300px" }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{title}</div>
      {rows.length === 0 ? <div style={hint}>Belum ada SPL.</div> : (
        <table className="data-table">
          <thead><tr><th>{title.replace("Per ", "")}</th><th>SPL</th><th>Orang-hari</th><th>Jam</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.name}><td>{r.name}</td><td>{r.orders}</td><td>{r.person_days}</td><td>{hours(r.minutes)}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontWeight: 800, color: "var(--midnight)" }}>Rekap periode ini</div>
          <div style={hint}>
            Lembur dibayar {hours(s.total_minutes)} · tanpa SPL {hours(s.no_spl_minutes)}
            {s.over_limit > 0 ? ` · ${s.over_limit} orang melebihi batas UU` : ""}. Jam sesuai yang dibayar payroll.
          </div>
        </div>
        <button className="btn-ghost" onClick={download}>Unduh CSV</button>
      </div>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 12 }}>
        {table("Per atasan", s.by_issuer)}
        {table("Per pekerjaan", s.by_work)}
      </div>
      <div style={{ fontWeight: 700, margin: "14px 0 4px" }}>Per karyawan</div>
      {s.by_person.length === 0 ? <div style={hint}>Belum ada lembur dibayar di periode ini.</div> : (
        <table className="data-table">
          <thead><tr><th>Karyawan</th><th>Hari lembur</th><th>Jam</th><th>Batas UU (4 jam sehari, 18 jam seminggu)</th></tr></thead>
          <tbody>{s.by_person.map((p) => (
            <tr key={p.employee.id}>
              <td>{p.employee.full_name}<div style={hint}>{p.employee.employee_no}</div></td>
              <td>{p.days}</td><td>{hours(p.minutes)}</td>
              <td style={{ fontSize: 13 }}>
                {p.long_days.length === 0 && p.heavy_weeks.length === 0 ? <span style={{ color: "#2E7D4F" }}>sesuai</span> : (
                  <span style={{ color: "#2563A8" }}>
                    <Info size={12} style={{ verticalAlign: "-1px" }} />{" "}
                    {p.long_days.length > 0 && `${p.long_days.length} hari > 4 jam (${p.long_days.map(dateText).join(", ")})`}
                    {p.long_days.length > 0 && p.heavy_weeks.length > 0 && "; "}
                    {p.heavy_weeks.length > 0 && `minggu ${p.heavy_weeks.map((w) => `${dateText(w.week)} (${hours(w.minutes)})`).join(", ")} > 18 jam`}
                  </span>
                )}
              </td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <div style={hint}>UU No. 27/2026 Pasal 116 ayat 1 huruf c. Tetap dibayar sesuai finger; sektor tertentu bisa dikecualikan (ayat 4).</div>
    </div>
  );
}

function SplDialog({ data, id, initial, month, onClose, onDone }: {
  data: SplPage; id: string | null; initial: SplInput; month?: string;
  onClose: () => void; onDone: (p: SplPage) => void;
}) {
  const [form, setForm] = useState<SplInput>(initial);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof SplInput>(k: K, v: SplInput[K]) => setForm({ ...form, [k]: v });
  const shown = useMemo(() => data.people.filter((p) =>
    !q || p.full_name.toLowerCase().includes(q.toLowerCase()) || p.employee_no.toLowerCase().includes(q.toLowerCase())), [data.people, q]);
  const toggle = (pid: string) => set("employee_ids",
    form.employee_ids.includes(pid) ? form.employee_ids.filter((x) => x !== pid) : [...form.employee_ids, pid]);

  const save = async () => {
    setBusy(true); setError(null);
    try { onDone(id ? await splApi.update(id, form, month) : await splApi.create(form, month)); }
    catch (e) { setError(readErrors(e).summary); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(1,61,90,.35)", display: "grid", placeItems: "center", zIndex: 50 }}>
      <div className="card" style={{ width: "min(720px, 94vw)", maxHeight: "92vh", overflow: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--midnight)" }}>{id ? "Ubah SPL" : "Catat SPL"}</div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none", color: "var(--steel)" }}><X size={18} /></button>
        </div>
        <div style={hint}>Dari SPL kertas yang ditandatangani atasan. Boleh dicatat sesudah lemburnya.</div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
          <div><label className="label">Tanggal mulai</label>
            <input type="date" className="input" style={{ width: "100%" }} value={form.start_date}
                   onChange={(e) => setForm({ ...form, start_date: e.target.value, end_date: e.target.value > form.end_date ? e.target.value : form.end_date })} /></div>
          <div><label className="label">Sampai</label>
            <input type="date" className="input" style={{ width: "100%" }} value={form.end_date} onChange={(e) => set("end_date", e.target.value)} /></div>
        </div>
        <label className="label" style={{ marginTop: 10 }}>Pekerjaan</label>
        <input className="input" style={{ width: "100%" }} placeholder="mis. Cor lantai 2 proyek X" value={form.work} onChange={(e) => set("work", e.target.value)} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 10 }}>
          <div><label className="label">Rencana mulai</label>
            <input type="time" className="input" style={{ width: "100%" }} value={form.planned_start ?? ""} onChange={(e) => set("planned_start", e.target.value || null)} /></div>
          <div><label className="label">Rencana selesai</label>
            <input type="time" className="input" style={{ width: "100%" }} value={form.planned_end ?? ""} onChange={(e) => set("planned_end", e.target.value || null)} /></div>
          <div><label className="label">Lokasi (boleh kosong)</label>
            <select className="input" style={{ width: "100%" }} value={form.site ?? ""} onChange={(e) => set("site", e.target.value || null)}>
              <option value="">-</option>
              {data.sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select></div>
        </div>
        <div style={hint}>Jam rencana hanya catatan; yang dibayar jam di finger. Ada catatan bila pulang lebih dari 1 jam setelah rencana.</div>
        <label className="label" style={{ marginTop: 10 }}>Dikeluarkan oleh (nama atasan)</label>
        <input className="input" style={{ width: "100%" }} placeholder="mis. SPV Plant" value={form.issued_by_name} onChange={(e) => set("issued_by_name", e.target.value)} />

        <div className="label" style={{ marginTop: 12 }}>Karyawan ({form.employee_ids.length} dipilih)</div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, border: "1px solid var(--line)", borderRadius: 6, padding: "4px 8px" }}>
          <Search size={14} style={{ color: "var(--steel)" }} />
          <input className="input" style={{ border: "none", padding: 4, flex: 1 }} placeholder="Cari nama atau no." value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div style={{ maxHeight: 200, overflow: "auto", border: "1px solid var(--line)", borderRadius: 6, marginTop: 6, padding: 6 }}>
          {shown.map((p) => (
            <label key={p.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "3px 4px", fontSize: 14,
                                       color: p.overtime_eligible ? undefined : "var(--steel)" }}>
              <input type="checkbox" disabled={!p.overtime_eligible} checked={form.employee_ids.includes(p.id)} onChange={() => toggle(p.id)} />
              {p.full_name} <span style={{ fontSize: 12, color: "var(--steel)" }}>{p.employee_no}{p.overtime_eligible ? "" : " · tidak berhak upah lembur"}</span>
            </label>
          ))}
        </div>

        <label style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 12, fontSize: 14 }}>
          <input type="checkbox" checked={form.consent === "yes"} onChange={(e) => set("consent", e.target.checked ? "yes" : "pending")} />
          <span>Semua karyawan di SPL ini sudah setuju (tanda tangan di SPL kertas)
            <div style={hint}>UU No. 27/2026 Pasal 116 ayat 1 huruf a. Bila belum, lembur tetap dihitung dengan catatan.</div></span>
        </label>

        <label className="label" style={{ marginTop: 10 }}>Foto SPL kertas (JPG/PNG/PDF, maks. 5 MB, boleh kosong)</label>
        <input type="file" accept=".jpg,.jpeg,.png,.webp,.pdf" onChange={(e) => set("attachment", e.target.files?.[0] ?? null)} />
        <label className="label" style={{ marginTop: 10 }}>Catatan (boleh kosong)</label>
        <input className="input" style={{ width: "100%" }} value={form.note} onChange={(e) => set("note", e.target.value)} />

        {error && <div style={{ color: "var(--danger)", fontSize: 13.5, marginTop: 10 }}>{error}</div>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
          <button className="btn-ghost" onClick={onClose}>Batal</button>
          <button className="btn-rust" onClick={save} disabled={busy || !form.work.trim() || form.employee_ids.length === 0}>
            {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : null} Simpan
          </button>
        </div>
      </div>
    </div>
  );
}
