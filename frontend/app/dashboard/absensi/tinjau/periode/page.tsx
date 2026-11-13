"use client";
// =============================================================================
// /dashboard/absensi/tinjau/periode — Tinjau massal per periode (G11, 4 Nov 2026).
// A whole pay period (26 - 25) of days waiting for HR, filtered by kind (Lembur,
// Terlambat, Tidak absen pulang ...), decided many at once:
//   tick rows (or "pilih semua yang cocok"), then Setujui or Tolak.
// G12g (8 Nov 2026): overtime is approved as the taps propose. A cap only when HR sets one (it starts
// from Pengaturan payroll, empty = none); every day it cuts is listed after the action, and days over
// PP 35's 4 hours on a working day are flagged (orange) as a warning, not cut.
// Click a row to open the day itself, as on the normal queue.
// G12f.3.2: HR's note from the recap shows in "Kenapa"; "Ada catatan HR" / "Tanpa catatan" filter the list,
// and "pilih semua yang cocok" sends the same filter, so a bulk decision covers exactly what is listed.
// =============================================================================
import DayPanel, { StatusPill } from "@/components/DayPanel";
import { HrNoteLine } from "@/components/HrNote";
import { BulkTrimmed, DayRow, ReviewPeriodData, attendanceApi, minutesText } from "@/lib/api/attendance";
import { readErrors } from "@/lib/api/hr";
import { Check, CheckCircle2, ChevronLeft, ChevronRight, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

const MON = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
function periodText(start: string, end: string): string {
  const [y1, m1, d1] = start.split("-").map(Number);
  const [y2, m2, d2] = end.split("-").map(Number);
  return `${d1} ${MON[m1 - 1]}${y1 !== y2 ? ` ${y1}` : ""} – ${d2} ${MON[m2 - 1]} ${y2}`;
}

type Mode = null | "approve" | "reject";

function trimmedText(list: BulkTrimmed[], total: number): string {                  // G12g
  const shown = list.slice(0, 5).map((t) => `${t.name} ${t.date.slice(8, 10)}-${t.date.slice(5, 7)} (${t.proposed}→${t.approved})`);
  return shown.join(", ") + (total > shown.length ? `, +${total - shown.length} lainnya` : "");
}

export default function TinjauPeriodePage() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [kind, setKind] = useState("");
  const [hasNote, setHasNote] = useState<"" | "1" | "0">("");               // G12f.3.2
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ReviewPeriodData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [allMatching, setAllMatching] = useState(false);
  const [mode, setMode] = useState<Mode>(null);
  const [note, setNote] = useState("");
  const [cap, setCap] = useState("");                     // G12g: empty = no cap
  const capTouched = useRef(false);                        // until HR types, the cap follows Pengaturan
  const seen = useRef(new Map<string, boolean>());         // day id -> over 4 h on a working day
  const [waiveLate, setWaiveLate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [open, setOpen] = useState<DayRow | null>(null);

  useEffect(() => { const t = setTimeout(() => { setQuery(q.trim()); setPage(1); }, 350); return () => clearTimeout(t); }, [q]);

  const clearPick = () => {
    setPicked(new Set()); setAllMatching(false); setMode(null); setWaiveLate(false);
    capTouched.current = false;                            // back to the company setting after each action
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await attendanceApi.reviewPeriod({ month, kind: kind || undefined, q: query || undefined, page,
                                                   has_note: hasNote || undefined });
      setData(d); setError(null);
      d.rows.forEach((r) => { if (r.day_id) seen.current.set(r.day_id, r.over_legal); });
      if (!capTouched.current) setCap(d.cap_minutes == null ? "" : String(d.cap_minutes));
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setLoading(false);
    }
  }, [month, kind, query, page, hasNote]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { clearPick(); }, [month, kind, query, hasNote]);

  const rows = data?.rows ?? [];
  const pageIds = rows.map((r) => r.day_id!).filter(Boolean);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => picked.has(id));
  const count = allMatching ? data?.total ?? 0 : picked.size;
  const overCount = allMatching ? data?.over_legal ?? 0 : Array.from(picked).filter((id) => seen.current.get(id)).length;
  const capMinutes = cap.trim() === "" ? null : Math.max(0, Math.round(Number(cap)));

  const toggle = (id: string) => {
    setAllMatching(false);
    setPicked((cur) => { const n = new Set(cur); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  };
  const togglePage = () => {
    setAllMatching(false);
    setPicked((cur) => { const n = new Set(cur); pageIds.forEach((id) => (allOnPage ? n.delete(id) : n.add(id))); return n; });
  };

  const decide = async () => {
    if (!data || !mode) return;
    setBusy(true); setError(null);
    try {
      const r = await attendanceApi.bulkDecide({                    // the cap is always sent explicitly
        action: mode, note, waive_late: mode === "approve" ? waiveLate : false, overtime_max_minutes: capMinutes,
        ...(allMatching ? { month: data.month, kind: kind || "", q: query, has_note: hasNote } : { ids: Array.from(picked) }),
      });
      setDone(`${r.decided} hari ${mode === "approve" ? "disetujui" : "ditolak"}` +
              (mode === "approve" && waiveLate ? " · terlambat dimaafkan (tanpa denda)" : "") +
              (r.overtime_minutes ? ` · lembur ${minutesText(r.overtime_minutes)}` : "") +
              (r.trimmed_count ? ` · ${r.trimmed_count} hari DIPOTONG ke ${r.cap_minutes} menit: ${trimmedText(r.trimmed, r.trimmed_count)}` : "") +
              (r.over_legal_days ? ` · ${r.over_legal_days} hari lembur > 4 jam (peringatan PP 35/2021)` : "") +
              (r.skipped ? ` · ${r.skipped} dilewati (terkunci / sudah diputuskan)` : ""));
      clearPick(); setNote("");
      setData(null);                      // no stale rows while the list reloads
      await load();
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Tinjau per periode</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14 }}>
            Semua hari yang menunggu keputusan HR dalam satu periode gaji. Saring per jenis, centang, lalu putuskan sekaligus.{" "}
            <Link href="/dashboard/absensi/tinjau" style={{ color: "var(--rust)" }}>← Antrean harian</Link>
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button className="btn-ghost" disabled={!data} onClick={() => data && (setMonth(data.prev), setPage(1))} style={{ padding: "6px 8px" }} aria-label="Periode sebelumnya"><ChevronLeft size={16} /></button>
          <div style={{ minWidth: 190, textAlign: "center" }}>
            <div style={{ fontWeight: 800, color: "var(--midnight)" }}>{data ? `Periode ${data.label}` : "…"}</div>
            {data && <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{periodText(data.start, data.end)}</div>}
          </div>
          <button className="btn-ghost" disabled={!data} onClick={() => data && (setMonth(data.next), setPage(1))} style={{ padding: "6px 8px" }} aria-label="Periode berikutnya"><ChevronRight size={16} /></button>
        </div>
      </div>

      {/* kinds = filters */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
        <button className="pill" onClick={() => { setKind(""); setPage(1); }}
                style={{ border: "1px solid var(--line)", cursor: "pointer", padding: "6px 12px", fontSize: 13.5,
                         background: kind === "" ? "var(--ink)" : "var(--paper-3)", color: kind === "" ? "var(--paper)" : "var(--ink)" }}>
          Semua {data ? `(${data.all})` : ""}
        </button>
        {(data?.kinds ?? []).map((k) => (
          <button key={k.key} className="pill" onClick={() => { setKind(k.key); setPage(1); }}
                  style={{ border: "1px solid var(--line)", cursor: "pointer", padding: "6px 12px", fontSize: 13.5,
                           background: kind === k.key ? "var(--ink)" : "var(--paper-3)", color: kind === k.key ? "var(--paper)" : "var(--ink)" }}>
            {k.label} ({k.count})
          </button>
        ))}
        {data && ((data.with_note ?? 0) > 0 || hasNote) && (["1", "0"] as const).map((v) => (
          <button key={v} className="pill" onClick={() => { setHasNote(hasNote === v ? "" : v); setPage(1); }}
                  title="Catatan HR dari file rekap yang diimport"
                  style={{ border: "1px dashed var(--midnight)", cursor: "pointer", padding: "6px 12px", fontSize: 13.5,
                           background: hasNote === v ? "var(--midnight)" : "transparent", color: hasNote === v ? "#fff" : "var(--midnight)" }}>
            {v === "1" ? `Ada catatan HR (${data.with_note ?? 0})` : "Tanpa catatan HR"}
          </button>
        ))}
        <input className="input" placeholder="Cari nama atau no. karyawan" value={q} onChange={(e) => setQ(e.target.value)}
               style={{ width: 240, marginLeft: "auto" }} />
      </div>

      {done && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12, background: "var(--workshop-lt)", color: "var(--workshop)", fontWeight: 700,
                                       display: "flex", alignItems: "center", gap: 8 }}>
          <CheckCircle2 size={16} /> {done}
          <button onClick={() => setDone(null)} aria-label="Tutup" style={{ marginLeft: "auto", background: "none", border: "none", color: "inherit" }}><X size={15} /></button>
        </div>
      )}
      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      {/* the bulk bar */}
      {count > 0 && (
        <div className="card" style={{ padding: "12px 16px", marginBottom: 12, borderColor: "var(--midnight)", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <b>{count} hari dipilih</b>
            {!allMatching && data && allOnPage && data.total > pageIds.length && (
              <button className="btn-ghost" onClick={() => setAllMatching(true)} style={{ padding: "3px 10px", fontSize: 13 }}>
                Pilih semua {data.total} yang cocok
              </button>
            )}
            {allMatching && <span style={{ fontSize: 13, color: "var(--steel)" }}>(semua yang cocok dengan saringan ini, di semua halaman)</span>}
            <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
              <button className="btn-rust" onClick={() => setMode("approve")} style={{ display: "flex", alignItems: "center", gap: 6 }}><Check size={15} /> Setujui</button>
              <button className="btn-ghost" onClick={() => setMode("reject")} style={{ display: "flex", alignItems: "center", gap: 6 }}><X size={15} /> Tolak</button>
              <button className="btn-ghost" onClick={clearPick}>Batal pilih</button>
            </span>
          </div>
          {mode && (
            <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", borderTop: "1px solid var(--line)", paddingTop: 10 }}>
              {mode === "approve" && (
                <>
                  <div><label className="label">Batasi lembur per hari kerja (menit)</label>
                    <input className="input" inputMode="numeric" value={cap} placeholder="tanpa batas" style={{ width: 140 }}
                           onChange={(e) => { capTouched.current = true; setCap(e.target.value.replace(/\D/g, "").slice(0, 4)); }} /></div>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13.5, paddingBottom: 10 }}>
                    <input type="checkbox" checked={waiveLate} onChange={(e) => setWaiveLate(e.target.checked)} /> Maafkan terlambat / tap sekali (tanpa potongan)
                  </label>
                </>
              )}
              <div style={{ flex: 1, minWidth: 220 }}><label className="label">{mode === "reject" ? "Alasan (wajib)" : "Catatan (opsional)"}</label>
                <input className="input" value={note} onChange={(e) => setNote(e.target.value)}
                       placeholder={mode === "reject" ? "mis. titip absen" : "mis. sesuai SPL bulan ini"} /></div>
              <button className="btn-rust" disabled={busy || (mode === "reject" && !note.trim())} onClick={decide}
                      style={{ display: "flex", alignItems: "center", gap: 6,
                               background: mode === "reject" ? "var(--danger)" : (waiveLate || capMinutes != null) ? "var(--hazard-dark)" : undefined }}>
                {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
                {mode === "approve"
                  ? `Setujui ${count} hari${capMinutes != null ? ` (lembur maks. ${capMinutes} menit/hari)` : ""}${waiveLate ? " + maafkan terlambat" : ""}`
                  : `Tolak ${count} hari`}
              </button>
            </div>
          )}
          {mode === "approve" && (
            <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
              {capMinutes == null
                ? "Lembur disetujui penuh, sebesar usulan dari jam absen."
                : `Lembur disetujui sebesar usulan dari jam absen, paling banyak ${capMinutes} menit per hari kerja (masuk di hari libur tidak dibatasi). Kosongkan kolom batas untuk menyetujui penuh.`}{" "}
              Terlambat tetap didenda kecuali dimaafkan. Hari yang punya beberapa alasan
              (mis. Terlambat + Tidak absen pulang) disetujui untuk semua alasannya.
            </div>
          )}
          {mode === "approve" && overCount > 0 && (
            <div style={{ fontSize: 13, color: "var(--hazard-dark)", fontWeight: 600 }}>
              {overCount} hari lembur lebih dari 4 jam di hari kerja (batas PP 35/2021).{" "}
              {capMinutes == null
                ? "Jam yang sudah dikerjakan tetap dibayar; payroll menampilkan peringatannya."
                : `Dengan batas ${capMinutes} menit, lembur di atas batas itu DIPOTONG (tidak dibayar).`}
            </div>
          )}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: open ? "minmax(0, 1fr) 460px" : "1fr", gap: 18, alignItems: "start" }}>
        <div className="card" style={{ padding: 0, opacity: loading ? 0.6 : 1 }}>
          {loading && !data ? (
            <div style={{ padding: 24 }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
          ) : rows.length === 0 ? (
            <div style={{ padding: 24, display: "flex", alignItems: "center", gap: 8 }}>
              <CheckCircle2 size={18} style={{ color: "var(--workshop)" }} /> <b>Semua beres</b> untuk periode ini{kind ? " dan jenis ini" : ""}.
            </div>
          ) : (
            <>
              <table className="data-table">
                <thead><tr>
                  <th style={{ width: 36 }}><input type="checkbox" aria-label="Pilih semua di halaman ini" checked={allOnPage} onChange={togglePage} /></th>
                  <th>Tanggal</th><th>Karyawan</th><th>Status</th><th>Kenapa</th><th>Lembur</th>
                </tr></thead>
                <tbody>
                  {rows.map((r) => {
                    const id = r.day_id!;
                    const isOpen = open && open.employee.id === r.employee.id && open.date === r.date;
                    return (
                      <tr key={id} style={{ cursor: "pointer", background: isOpen ? "var(--paper)" : picked.has(id) || allMatching ? "var(--midnight-soft)" : undefined }}>
                        <td onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" aria-label={`Pilih ${r.employee.full_name} ${r.date}`} checked={allMatching || picked.has(id)} onChange={() => toggle(id)} />
                        </td>
                        <td className="mono" style={{ fontSize: 13, whiteSpace: "nowrap" }} onClick={() => setOpen(r)}>{r.date}</td>
                        <td onClick={() => setOpen(r)}><div style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{r.employee.full_name}</div>
                          <div className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>{r.employee.employee_no}</div></td>
                        <td onClick={() => setOpen(r)}><StatusPill status={r.status} label={r.status_label} /></td>
                        <td style={{ fontSize: 13, ...(open ? { maxWidth: 200, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } : {}) }}
                            title={r.review_reasons.join(" · ")} onClick={() => setOpen(r)}>
                          {r.hr_note && <div><HrNoteLine note={r.hr_note} maxWidth={open ? 200 : 360} /></div>}
                          {r.review_reasons.join(" · ")}</td>
                        <td style={{ fontSize: 13, whiteSpace: "nowrap", color: r.over_legal ? "var(--hazard-dark)" : undefined }}
                            title={r.over_legal ? "Lebih dari 4 jam di hari kerja (batas PP 35/2021): peringatan, tetap dibayar" : undefined}
                            onClick={() => setOpen(r)}>
                          {r.overtime_proposed_minutes ? minutesText(r.overtime_proposed_minutes) : "-"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {data && data.pages > 1 && (
                <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, padding: 10, borderTop: "1px solid var(--line)" }}>
                  <span style={{ fontSize: 13, color: "var(--steel)", marginRight: "auto" }}>{data.total} hari</span>
                  <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
                  <span style={{ fontSize: 13 }}>Hal. {data.page} / {data.pages}</span>
                  <button className="btn-ghost" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>›</button>
                </div>
              )}
            </>
          )}
        </div>
        {open && <DayPanel key={`${open.employee.id}-${open.date}`} row={open} onChanged={() => load()} onClose={() => setOpen(null)} />}
      </div>
    </div>
  );
}
