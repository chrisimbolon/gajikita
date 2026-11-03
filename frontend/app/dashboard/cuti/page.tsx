"use client";
// =============================================================================
// /dashboard/cuti — Cuti & Izin for HR (G7, 28 Oct 2026).
//
//   Requests from the workers' phones wait for their site manager (mandor / atasan)
//   or HR. HR can decide any of them, cancel approved leave, see the doctor's
//   letter, and record a paper form (approved straight away).
// =============================================================================
import { Employee, hrApi, readErrors } from "@/lib/api/hr";
import {
  AnnualBalance, HrLeaveList, Leave, LeaveKind, LeaveStatus, LEAVE_STATUS_STYLE, hrLeaveApi, periodText,
} from "@/lib/api/leave";
import { dateTimeWIB, todayISO } from "@/lib/format";
import { AlertTriangle, FilePlus2, Loader2, Paperclip, Search, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

const TABS: { key: LeaveStatus | "all"; label: string }[] = [
  { key: "pending", label: "Menunggu" }, { key: "approved", label: "Disetujui" }, { key: "rejected", label: "Ditolak" },
  { key: "cancelled", label: "Dibatalkan" }, { key: "all", label: "Semua" },
];

const overlay = { position: "fixed", inset: 0, background: "rgba(1,61,90,0.45)", zIndex: 50, display: "flex",
                  alignItems: "center", justifyContent: "center", padding: 16 } as const;

function Pill({ l }: { l: Leave }) {
  const s = LEAVE_STATUS_STYLE[l.status];
  return <span className="pill" style={{ background: s.bg, color: s.fg }}>{l.status_label}</span>;
}

// ── reject / cancel with a note ──
function NoteDialog({ leave, action, onClose, onDone }: {
  leave: Leave; action: "reject" | "cancel"; onClose: () => void; onDone: (msg: string) => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setBusy(true);
    try { await hrLeaveApi.decide(leave.id, action, note); onDone(`${leave.employee.full_name}: ${action === "reject" ? "ditolak" : "dibatalkan"}.`); }
    catch (err) { setError(readErrors(err).summary); setBusy(false); }
  };
  return (
    <div style={overlay} onClick={onClose}>
      <div className="card" style={{ width: 420, maxWidth: "100%", padding: 20 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ fontSize: 17, fontWeight: 800, color: "var(--midnight)" }}>
          {action === "reject" ? "Tolak pengajuan" : "Batalkan cuti"}
        </div>
        <div style={{ fontSize: 13.5, color: "var(--steel)", margin: "4px 0 12px" }}>
          {leave.employee.full_name} · {leave.label} · {periodText(leave.start_date, leave.end_date)}
          {action === "cancel" && leave.status === "approved" ? ". Hari-hari itu kembali dihitung tidak hadir jika tidak absen." : ""}
        </div>
        <textarea className="input" rows={3} value={note} onChange={(e) => setNote(e.target.value)} style={{ width: "100%" }}
                  placeholder={action === "reject" ? "Alasan penolakan (wajib)" : "Catatan (boleh kosong)"} autoFocus />
        {error && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 6 }}>{error}</div>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
          <button className="btn-ghost" onClick={onClose}>Kembali</button>
          <button className="btn-rust" disabled={busy || (action === "reject" && !note.trim())} onClick={go}
                  style={{ background: "var(--danger)" }}>
            {action === "reject" ? "Tolak" : "Batalkan cuti"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── the paper form ──
function PaperFormDialog({ data, onClose, onDone }: { data: HrLeaveList; onClose: () => void; onDone: (msg: string) => void }) {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [employee, setEmployee] = useState("");
  const [balance, setBalance] = useState<AnnualBalance | null>(null);
  const [kind, setKind] = useState<LeaveKind>("annual");
  const [special, setSpecial] = useState("");
  const [start, setStart] = useState(todayISO());
  const [end, setEnd] = useState(todayISO());
  const [reason, setReason] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<{ fields: Record<string, string>; summary: string } | null>(null);

  useEffect(() => { hrApi.employees().then((list) => setEmployees(list.filter((e) => e.status === "active"))).catch(() => {}); }, []);
  useEffect(() => {
    setBalance(null);
    if (employee) hrLeaveApi.balance(employee).then(setBalance).catch(() => {});
  }, [employee]);

  const save = async () => {
    setBusy(true);
    setErrors(null);
    try {
      const l = await hrLeaveApi.record(employee, {
        kind, special_reason: special, start_date: start, end_date: end < start ? start : end, reason,
        attachment: file ? { blob: file, name: file.name } : null,
      });
      onDone(`${l.employee.full_name}: ${l.label} ${periodText(l.start_date, l.end_date)} (${l.days} hari kerja) dicatat dan disetujui.`);
    } catch (err) {
      setErrors(readErrors(err));
      setBusy(false);
    }
  };

  const field = (name: string) => errors?.fields[name] &&
    <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 4 }}>{errors.fields[name]}</div>;

  return (
    <div style={overlay} onClick={onClose}>
      <div className="card" style={{ width: 520, maxWidth: "100%", padding: 22, maxHeight: "92vh", overflowY: "auto" }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 18, fontWeight: 800, color: "var(--midnight)" }}>Catat formulir cuti</div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none" }}><X size={18} /></button>
        </div>
        <div style={{ fontSize: 13.5, color: "var(--steel)", margin: "4px 0 16px" }}>
          Dari formulir kertas yang sudah ditandatangani atasan. Langsung disetujui.
        </div>

        <label style={{ display: "block", marginBottom: 12 }}>
          <div className="label">Karyawan</div>
          <select className="input" value={employee} onChange={(e) => setEmployee(e.target.value)} style={{ width: "100%" }}>
            <option value="">Pilih karyawan…</option>
            {employees.map((e) => <option key={e.id} value={e.id}>{e.full_name} ({e.employee_no})</option>)}
          </select>
          {field("employee")}
        </label>

        <label style={{ display: "block", marginBottom: 12 }}>
          <div className="label">Jenis</div>
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value as LeaveKind)} style={{ width: "100%" }}>
            {data.kinds.map((k) => <option key={k.value} value={k.value}>{k.label}{k.paid ? "" : " (tidak dibayar)"}</option>)}
          </select>
          {kind === "annual" && balance && (
            <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 4 }}>
              {balance.entitled > 0 ? `Sisa cuti tahunan ${balance.year}: ${balance.left} dari ${balance.entitled} hari`
                                    : `Belum berhak cuti tahunan (mulai ${periodText(balance.from_date, balance.from_date)})`}
            </div>
          )}
        </label>

        {kind === "special" && (
          <label style={{ display: "block", marginBottom: 12 }}>
            <div className="label">Alasan cuti khusus</div>
            <select className="input" value={special} onChange={(e) => setSpecial(e.target.value)} style={{ width: "100%" }}>
              <option value="">Pilih…</option>
              {data.special_reasons.map((r) => <option key={r.value} value={r.value}>{r.label} ({r.days} hari)</option>)}
            </select>
            {field("special_reason")}
          </label>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
          <label>
            <div className="label">Mulai</div>
            <input className="input" type="date" value={start} style={{ width: "100%" }}
                   onChange={(e) => { setStart(e.target.value); if (e.target.value > end) setEnd(e.target.value); }} />
            {field("start_date")}
          </label>
          <label>
            <div className="label">Sampai</div>
            <input className="input" type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} style={{ width: "100%" }} />
            {field("end_date")}
          </label>
        </div>

        <label style={{ display: "block", marginBottom: 12 }}>
          <div className="label">Keterangan</div>
          <input className="input" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} style={{ width: "100%" }} />
        </label>

        <label style={{ display: "block", marginBottom: 4 }}>
          <div className="label">Lampiran (surat dokter / scan formulir, JPG/PNG/PDF, maks. 5 MB)</div>
          <input type="file" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          {field("attachment")}
        </label>

        {errors?.summary && !Object.keys(errors.fields).length && (
          <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 10 }}>{errors.summary}</div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
          <button className="btn-ghost" onClick={onClose}>Batal</button>
          <button className="btn-rust" disabled={busy || !employee || (kind === "special" && !special)} onClick={save}>
            {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />} Simpan & setujui
          </button>
        </div>
      </div>
    </div>
  );
}

function AttachmentViewer({ leave, onClose }: { leave: Leave; onClose: () => void }) {
  const [file, setFile] = useState<{ url: string; isPdf: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let made: string | null = null;
    hrLeaveApi.attachment(leave.id).then((f) => { made = f.url; setFile(f); }).catch((err) => setError(readErrors(err).summary));
    return () => { if (made) URL.revokeObjectURL(made); };
  }, [leave.id]);
  return (
    <div style={overlay} onClick={onClose}>
      <div className="card" style={{ width: 760, maxWidth: "100%", padding: 14 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <div style={{ fontWeight: 700 }}>{leave.employee.full_name} · {leave.label} · {periodText(leave.start_date, leave.end_date)}</div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none" }}><X size={18} /></button>
        </div>
        {error && <div style={{ color: "var(--danger)" }}>{error}</div>}
        {!file && !error && <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />}
        {file && (file.isPdf
          ? <iframe src={file.url} title="Lampiran" style={{ width: "100%", height: "75vh", border: "none" }} />
          : <img src={file.url} alt="Lampiran" style={{ maxWidth: "100%", maxHeight: "75vh", display: "block", margin: "0 auto" }} />)}
      </div>
    </div>
  );
}

export default function CutiPage() {
  const [tab, setTab] = useState<LeaveStatus | "all">("pending");
  const [q, setQ] = useState("");
  const [data, setData] = useState<HrLeaveList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [noteFor, setNoteFor] = useState<{ leave: Leave; action: "reject" | "cancel" } | null>(null);
  const [paper, setPaper] = useState(false);
  const [viewing, setViewing] = useState<Leave | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async (t: LeaveStatus | "all", query: string) => {
    setLoading(true);
    try { setData(await hrLeaveApi.list(t, query)); setError(null); }
    catch (err) { setError(readErrors(err).summary); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => load(tab, q.trim()), q ? 300 : 0);
    return () => window.clearTimeout(timer);
  }, [tab, q, load]);

  const done = async (msg: string) => {
    setNoteFor(null); setPaper(false); setFlash(msg);
    await load(tab, q.trim());
  };

  const approve = async (l: Leave) => {
    setBusyId(l.id);
    try { await hrLeaveApi.decide(l.id, "approve"); await done(`${l.employee.full_name}: ${l.label} disetujui.`); }
    catch (err) { setFlash(null); setError(readErrors(err).summary); }
    finally { setBusyId(null); }
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 14, gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Cuti & Izin</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14, maxWidth: 640 }}>
            Pengajuan dari HP karyawan menunggu atasannya (mandor) atau HR. Cuti yang disetujui tampil di Absensi
            sebagai cuti, bukan tidak hadir.
          </p>
        </div>
        <button className="btn-rust" onClick={() => setPaper(true)} disabled={!data}
                style={{ display: "flex", alignItems: "center", gap: 6 }}><FilePlus2 size={16} /> Catat formulir</button>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {TABS.map((t) => {
            const on = tab === t.key;
            const n = data && t.key !== "all" ? data.counts[t.key] : null;
            return (
              <button key={t.key} onClick={() => setTab(t.key)} style={{
                padding: "7px 14px", borderRadius: 999, fontSize: 13.5, fontWeight: 700, cursor: "pointer",
                border: on ? "1px solid var(--midnight)" : "1px solid var(--line)",
                background: on ? "var(--midnight)" : "#FFFFFF", color: on ? "#FFFFFF" : "var(--ink)",
              }}>
                {t.label}
                {n !== null && n > 0 && (
                  <span style={{ marginLeft: 6, padding: "0 7px", borderRadius: 999, fontSize: 12,
                                 background: t.key === "pending" ? "var(--marigold)" : on ? "rgba(255,255,255,0.2)" : "var(--paper-2)",
                                 color: t.key === "pending" ? "var(--midnight)" : "inherit" }}>{n}</span>
                )}
              </button>
            );
          })}
        </div>
        <div style={{ position: "relative" }}>
          <Search size={15} style={{ position: "absolute", left: 10, top: 11, color: "var(--steel)" }} />
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nama / no. karyawan"
                 style={{ paddingLeft: 32, width: 240 }} />
        </div>
      </div>

      {flash && <div style={{ background: "var(--workshop-lt)", color: "var(--workshop)", padding: "10px 14px", borderRadius: 8,
                              fontWeight: 600, fontSize: 14, marginBottom: 12 }}>{flash}</div>}
      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      {loading && !data ? (
        <div style={{ padding: 24, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
      ) : data && data.requests.length === 0 ? (
        <div className="card" style={{ color: "var(--steel)", fontSize: 14 }}>
          {tab === "pending" ? "Tidak ada pengajuan yang menunggu." : "Belum ada data."}
        </div>
      ) : data && (
        <div className="card" style={{ padding: 0, opacity: loading ? 0.6 : 1 }}>
          <table className="data-table">
            <thead><tr><th>Karyawan</th><th>Jenis</th><th>Tanggal</th><th>Hari</th><th>Keterangan</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {data.requests.map((l) => (
                <tr key={l.id}>
                  <td><div style={{ fontWeight: 600 }}>{l.employee.full_name}</div>
                    <div className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>{l.employee.employee_no}</div></td>
                  <td><div>{l.label}</div>
                    {!l.paid && <div style={{ fontSize: 12, color: "var(--hazard-dark)" }}>tidak dibayar</div>}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{periodText(l.start_date, l.end_date)}</td>
                  <td>{l.days}</td>
                  <td style={{ fontSize: 13, maxWidth: 260 }}>
                    {l.reason || <span style={{ color: "var(--steel)" }}>-</span>}
                    {l.has_attachment && (
                      <button onClick={() => setViewing(l)} style={{ display: "flex", alignItems: "center", gap: 4, background: "none",
                                                                     border: "none", color: "var(--rust)", padding: 0, marginTop: 4, fontSize: 13 }}>
                        <Paperclip size={13} /> Lihat lampiran
                      </button>
                    )}
                    {l.sick_note_missing && (
                      <div style={{ color: "var(--hazard-dark)", fontSize: 12.5, marginTop: 4 }}>
                        <AlertTriangle size={12} style={{ verticalAlign: "-1px" }} /> Sakit &gt; 2 hari tanpa surat dokter
                      </div>
                    )}
                  </td>
                  <td>
                    <Pill l={l} />
                    <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 4 }}>
                      {l.status === "pending"
                        ? `Menunggu ${l.approver ?? "HR"}`
                        : `${l.decided_by ?? ""}${l.decided_at ? ` · ${dateTimeWIB(l.decided_at)}` : ""}`}
                    </div>
                    {l.source === "form" && <div style={{ fontSize: 12, color: "var(--steel)" }}>Formulir kertas</div>}
                    {l.decision_note && l.status !== "pending" && (
                      <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>&ldquo;{l.decision_note}&rdquo;</div>
                    )}
                  </td>
                  <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                    {l.status === "pending" && (
                      <>
                        <button className="btn-ghost" onClick={() => setNoteFor({ leave: l, action: "reject" })}
                                style={{ padding: "6px 12px", fontSize: 13, marginRight: 6 }}>Tolak</button>
                        <button className="btn-rust" disabled={busyId === l.id} onClick={() => approve(l)}
                                style={{ padding: "6px 12px", fontSize: 13 }}>Setujui</button>
                      </>
                    )}
                    {l.status === "approved" && (
                      <button className="btn-ghost" onClick={() => setNoteFor({ leave: l, action: "cancel" })}
                              style={{ padding: "6px 12px", fontSize: 13 }}>Batalkan</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {noteFor && <NoteDialog leave={noteFor.leave} action={noteFor.action} onClose={() => setNoteFor(null)} onDone={done} />}
      {paper && data && <PaperFormDialog data={data} onClose={() => setPaper(false)} onDone={done} />}
      {viewing && <AttachmentViewer leave={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}
