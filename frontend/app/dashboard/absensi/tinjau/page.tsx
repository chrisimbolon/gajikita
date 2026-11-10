"use client";
// =============================================================================
// /dashboard/absensi/tinjau — HR's review queue (G3, 28 Oct 2026).
// Exceptions first: only the days that need HR (late, early out, no clock-out,
// outside site, overtime, a day-off shift...). Each opens the same DayPanel
// with approve / reject / fix times.
// =============================================================================
import DayPanel, { StatusPill } from "@/components/DayPanel";
import { HrNoteLine } from "@/components/HrNote";
import { DayRow, attendanceApi } from "@/lib/api/attendance";
import { readErrors } from "@/lib/api/hr";
import { CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const RANGES = [1, 7, 14, 31];

export default function TinjauPage() {
  const [days, setDays] = useState(7);
  const [rows, setRows] = useState<DayRow[]>([]);
  const [summary, setSummary] = useState<{ label: string; count: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<DayRow | null>(null);

  const load = useCallback(async (n: number) => {
    setLoading(true);
    try {
      const data = await attendanceApi.review(n);
      setRows(data.rows); setSummary(data.summary); setError(null);
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(days); }, [days, load]);

  // A decision takes the day out of the queue; keep the panel open so HR sees the result.
  const onChanged = (changed: DayRow) => {
    setRows((cur) => cur.filter((r) => !(r.employee.id === changed.employee.id && r.date === changed.date) || changed.needs_review));
    load(days);
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Perlu Tinjau</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14 }}>
            Hanya absen yang perlu keputusan HR. <Link href="/dashboard/absensi" style={{ color: "var(--rust)" }}>Lihat semua absensi →</Link>
            {" · "}<Link href="/dashboard/absensi/tinjau/periode" style={{ color: "var(--rust)", fontWeight: 700 }}>
              Tinjau per periode (massal) →</Link>
          </p>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {RANGES.map((n) => (
            <button key={n} onClick={() => setDays(n)} className="pill"
                    style={{ border: "1px solid var(--line)", cursor: "pointer", padding: "6px 12px",
                             background: days === n ? "var(--ink)" : "var(--paper-3)", color: days === n ? "var(--paper)" : "var(--ink)" }}>
              {n === 1 ? "Hari ini" : `${n} hari`}
            </button>
          ))}
        </div>
      </div>

      {/* the one-line summary: "Perlu tindakan: 3 Terlambat · 1 Tidak absen pulang · 1 Di luar lokasi" */}
      <div className="card" style={{ padding: "14px 18px", marginBottom: 14, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
                                     borderColor: rows.length ? "var(--hazard)" : undefined }}>
        {loading ? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> : rows.length === 0 ? (
          <><CheckCircle2 size={18} style={{ color: "var(--workshop)" }} /> <b>Semua beres.</b> Tidak ada absen yang perlu ditinjau.</>
        ) : (
          <><b>Perlu tindakan: {rows.length} hari</b>
            <span style={{ color: "var(--ink-soft)" }}>{summary.map((s) => `${s.count} ${s.label}`).join(" · ")}</span></>
        )}
      </div>

      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 14 }}>{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: open ? "minmax(0, 1fr) 460px" : "1fr", gap: 18, alignItems: "start" }}>
        {rows.length > 0 && (
          <div className="card" style={{ padding: 0 }}>
            <table className="data-table">
              <thead><tr><th>Tanggal</th><th>Karyawan</th><th>Status</th><th>Kenapa</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.employee.id}-${r.date}`} onClick={() => setOpen(r)} style={{ cursor: "pointer",
                      background: open && open.employee.id === r.employee.id && open.date === r.date ? "var(--paper)" : undefined }}>
                    <td className="mono" style={{ fontSize: 13, whiteSpace: "nowrap" }}>{r.date}</td>
                    <td><div style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{r.employee.full_name}</div>
                      <div className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>{r.employee.employee_no}</div></td>
                    <td><StatusPill status={r.status} label={r.status_label} /></td>
                    <td style={{ fontSize: 13 }}>
                      {r.hr_note && <div><HrNoteLine note={r.hr_note} maxWidth={360} /></div>}   {/* G12f.3.2 */}
                      {r.review_reasons.join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {open && <DayPanel key={`${open.employee.id}-${open.date}`} row={open} onChanged={onChanged} onClose={() => setOpen(null)} />}
      </div>
    </div>
  );
}
