"use client";
// =============================================================================
// /dashboard/absensi/tinjau/periode — Tinjau massal per periode (G11, 4 Nov 2026).
// A whole pay period (26 - 25) of days waiting for HR, filtered by kind (Lembur,
// Terlambat, Tidak absen pulang ...), decided many at once:
//   tick rows (or "pilih semua yang cocok"), then Setujui (overtime capped per day) or Tolak.
// Click a row to open the day itself, as on the normal queue.
// =============================================================================
import DayPanel, { StatusPill } from "@/components/DayPanel";
import { DayRow, ReviewPeriodData, attendanceApi, minutesText } from "@/lib/api/attendance";
import { readErrors } from "@/lib/api/hr";
import { Check, CheckCircle2, ChevronLeft, ChevronRight, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const MON = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
function periodText(start: string, end: string): string {
  const [y1, m1, d1] = start.split("-").map(Number);
  const [y2, m2, d2] = end.split("-").map(Number);
  return `${d1} ${MON[m1 - 1]}${y1 !== y2 ? ` ${y1}` : ""} – ${d2} ${MON[m2 - 1]} ${y2}`;
}

type Mode = null | "approve" | "reject";

export default function TinjauPeriodePage() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [kind, setKind] = useState("");
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
  const [cap, setCap] = useState("240");
  const [waiveLate, setWaiveLate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [open, setOpen] = useState<DayRow | null>(null);

  useEffect(() => { const t = setTimeout(() => { setQuery(q.trim()); setPage(1); }, 350); return () => clearTimeout(t); }, [q]);

  const clearPick = () => { setPicked(new Set()); setAllMatching(false); setMode(null); };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await attendanceApi.reviewPeriod({ month, kind: kind || undefined, q: query || undefined, page });
      setData(d); setError(null);
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setLoading(false);
    }
  }, [month, kind, query, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { clearPick(); }, [month, kind, query]);

  const rows = data?.rows ?? [];
  const pageIds = rows.map((r) => r.day_id!).filter(Boolean);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => picked.has(id));
  const count = allMatching ? data?.total ?? 0 : picked.size;

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
      const capMinutes = cap.trim() === "" ? null : Math.max(0, Math.round(Number(cap)));
      const r = await attendanceApi.bulkDecide({
        action: mode, note, waive_late: mode === "approve" ? waiveLate : false, overtime_max_minutes: capMinutes,
        ...(allMatching ? { month: data.month, kind: kind || "", q: query } : { ids: Array.from(picked) }),
      });
      setDone(`${r.decided} hari ${mode === "approve" ? "disetujui" : "ditolak"}` +
              (r.overtime_minutes ? ` · lembur ${minutesText(r.overtime_minutes)}` : "") +
              (r.skipped ? ` · ${r.skipped} dilewati (terkunci / sudah diputuskan)` : ""));
      clearPick(); setNote("");
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
                  <div><label className="label">Lembur maks. per hari (menit)</label>
                    <input className="input" inputMode="numeric" value={cap} onChange={(e) => setCap(e.target.value.replace(/\D/g, ""))} style={{ width: 120 }} /></div>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13.5, paddingBottom: 10 }}>
                    <input type="checkbox" checked={waiveLate} onChange={(e) => setWaiveLate(e.target.checked)} /> Maafkan terlambat (tanpa denda)
                  </label>
                </>
              )}
              <div style={{ flex: 1, minWidth: 220 }}><label className="label">{mode === "reject" ? "Alasan (wajib)" : "Catatan (opsional)"}</label>
                <input className="input" value={note} onChange={(e) => setNote(e.target.value)}
                       placeholder={mode === "reject" ? "mis. titip absen" : "mis. sesuai SPL bulan ini"} /></div>
              <button className="btn-rust" disabled={busy || (mode === "reject" && !note.trim())} onClick={decide}
                      style={{ display: "flex", alignItems: "center", gap: 6, background: mode === "reject" ? "var(--danger)" : undefined }}>
                {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
                {mode === "approve" ? `Setujui ${count} hari` : `Tolak ${count} hari`}
              </button>
            </div>
          )}
          {mode === "approve" && (
            <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
              Lembur disetujui sebesar usulan dari jam absen, paling banyak {cap || "∞"} menit per hari kerja (masuk di hari libur tidak
              dibatasi: semua jamnya lembur). Terlambat tetap didenda kecuali dimaafkan. Hari yang punya beberapa alasan
              (mis. Terlambat + Tidak absen pulang) disetujui untuk semua alasannya.
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
                            title={r.review_reasons.join(" · ")} onClick={() => setOpen(r)}>{r.review_reasons.join(" · ")}</td>
                        <td style={{ fontSize: 13, whiteSpace: "nowrap", color: r.overtime_proposed_minutes > 240 ? "var(--hazard-dark)" : undefined }}
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
