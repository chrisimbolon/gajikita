"use client";
// =============================================================================
// /dashboard/absensi/rekap — Rekap Absensi (G10, 1 Nov 2026).
// Everyone x every day of the pay period (e.g. 26 Sep - 25 Okt), like the machine's
// "Attendance Record Report", but each cell is clickable: it opens the same day panel
// as the daily page, so HR fixes a day right from the grid.
//   Kode view: H, T, A, C, S ... (with a dot when HR still has to review)
//   Jam view:  clock-in / clock-out times
// The summary columns use the same numbers as payroll.
// G12f.3.2: a cell with HR's note (from the imported recap) has a corner in the note's colour; the
// note is in the cell's tooltip and in the day panel.
// =============================================================================
import AbsensiTabs from "@/components/AbsensiTabs";
import DayPanel from "@/components/DayPanel";
import { noteTitle } from "@/components/HrNote";
import { DayRow, RekapCell, RekapData, RekapRow, attendanceApi, minutesText } from "@/lib/api/attendance";
import { Shift, Site, hrApi, readErrors } from "@/lib/api/hr";
import { ChevronLeft, ChevronRight, Download, Loader2 } from "lucide-react";
import { CSSProperties, useCallback, useEffect, useRef, useState } from "react";

const CODE_STYLE: Record<string, { bg: string; fg: string }> = {
  H:  { bg: "var(--workshop-lt)", fg: "var(--workshop)" },
  K:  { bg: "var(--workshop-lt)", fg: "var(--workshop)" },
  T:  { bg: "var(--hazard-light)", fg: "var(--hazard-dark)" },
  PC: { bg: "var(--hazard-light)", fg: "var(--hazard-dark)" },
  LK: { bg: "var(--hazard-light)", fg: "var(--hazard-dark)" },
  TP: { bg: "var(--danger-light)", fg: "#A3261C" },
  A:  { bg: "var(--danger-light)", fg: "#A3261C" },
  X:  { bg: "var(--danger-light)", fg: "var(--danger)" },
  C:  { bg: "var(--midnight-soft)", fg: "var(--midnight)" },
  S:  { bg: "var(--midnight-soft)", fg: "var(--midnight)" },
  CK: { bg: "var(--midnight-soft)", fg: "var(--midnight)" },
  I:  { bg: "var(--midnight-soft)", fg: "var(--midnight)" },
  L:  { bg: "var(--paper-2)", fg: "var(--steel)" },
  "-": { bg: "transparent", fg: "var(--line)" },
};
const NAME_W = 210;

function hours(m: number): string {
  if (!m) return "-";
  return (Math.round((m / 60) * 10) / 10).toString().replace(".", ",");
}

const MON = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

/** "26 Okt – 25 Nov 2026" */
function periodText(start: string, end: string): string {
  const [y1, m1, d1] = start.split("-").map(Number);
  const [y2, m2, d2] = end.split("-").map(Number);
  return `${d1} ${MON[m1 - 1]}${y1 !== y2 ? ` ${y1}` : ""} – ${d2} ${MON[m2 - 1]} ${y2}`;
}

/** A DayRow the day panel can open; the panel then loads the full day by its id. */
function toDayRow(row: RekapRow, cell: RekapCell): DayRow {
  return {
    employee: { id: row.employee.id, employee_no: row.employee.employee_no, full_name: row.employee.full_name },
    date: cell.d, day_id: cell.day, status: cell.s as DayRow["status"], status_label: cell.l, tags: [],
    first_in: cell.fi, last_out: cell.lo, late_minutes: cell.late, early_minutes: cell.early, worked_minutes: 0,
    overtime_proposed_minutes: cell.otp, overtime_approved_minutes: cell.ot || null, site_minutes: {},
    review_reasons: [], needs_review: cell.rv, decision: "", is_locked: false, hr_fixed: false,
    hr_note: cell.hn ?? null,                                                    // G12f.3.2
  };
}

/** G12f.3.2: the little corner that says "HR wrote a note here", in the note's own colour. */
function NoteCorner({ color }: { color: string }) {
  return <span style={{ position: "absolute", top: 0, left: 0, width: 0, height: 0,
                        borderTop: `8px solid ${color ? `#${color}` : "var(--steel)"}`, borderRight: "8px solid transparent",
                        filter: "drop-shadow(0 0 0.5px rgba(0,0,0,0.6))" }} />;
}

export default function RekapPage() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [view, setView] = useState<"kode" | "jam">("kode");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [site, setSite] = useState("");
  const [shift, setShift] = useState("");
  const [problems, setProblems] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<RekapData | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ row: DayRow; key: string } | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const [atSummary, setAtSummary] = useState(false);
  const jump = () => {
    const g = gridRef.current;
    if (g) g.scrollTo({ left: atSummary ? 0 : g.scrollWidth, behavior: "smooth" });
  };

  useEffect(() => {
    hrApi.sites().then(setSites).catch(() => setSites([]));
    hrApi.shifts().then(setShifts).catch(() => setShifts([]));
  }, []);

  // search waits until typing stops
  useEffect(() => { const t = setTimeout(() => { setQuery(q.trim()); setPage(1); }, 350); return () => clearTimeout(t); }, [q]);

  const params = { month, q: query || undefined, site: site || undefined, shift: shift || undefined,
                   problems: problems ? "1" : undefined, page };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await attendanceApi.rekap(params);
      setData(d); setError(null);
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month, query, site, shift, problems, page]);

  useEffect(() => { load(); }, [load]);

  const go = (m: string) => { setMonth(m); setPage(1); setOpen(null); };

  const exportExcel = async () => {
    if (!data) return;
    setExporting(true);
    try {
      await attendanceApi.exportRekap({ ...params, month: data.month, page: undefined }, `Rekap_Absensi_${data.label.replace(" ", "_")}.xlsx`);
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setExporting(false);
    }
  };

  const cellText = (c: RekapCell) => {
    if (view === "kode") return c.c;
    if (c.fi || c.lo) return <>{c.fi ?? "--:--"}<br />{c.lo ?? "--:--"}</>;
    return c.c;
  };

  const cellTitle = (r: RekapRow, c: RekapCell) => [
    `${r.employee.full_name} · ${c.d}`, c.l, c.n ?? "",
    c.fi || c.lo ? `Masuk ${c.fi ?? "-"} · Pulang ${c.lo ?? "-"}` : "",
    c.late ? `Terlambat ${minutesText(c.late)}` : "", c.early ? `Pulang cepat ${minutesText(c.early)}` : "",
    c.ot ? `Lembur disetujui ${minutesText(c.ot)}` : "", c.otp ? `Lembur menunggu ${minutesText(c.otp)}` : "",
    c.rv ? "Perlu ditinjau HR" : "", c.hn ? noteTitle(c.hn) : "",
  ].filter(Boolean).join("\n");

  const th: CSSProperties = { position: "sticky", top: 0, background: "var(--midnight)", color: "#fff", fontSize: 11.5,
                                    fontWeight: 700, padding: "6px 4px", textAlign: "center", zIndex: 2, whiteSpace: "nowrap" };
  const sumCols: { label: string; value: (r: RekapRow) => string | number; warn?: (r: RekapRow) => boolean }[] = [
    { label: "Hadir", value: (r) => r.summary.present },
    { label: "Telat (x)", value: (r) => r.summary.late_times || "-", warn: (r) => r.summary.late_times > 0 },
    { label: "Telat (mnt)", value: (r) => r.summary.late_minutes || "-", warn: (r) => r.summary.late_minutes > 0 },
    { label: "Plg cepat (mnt)", value: (r) => r.summary.early_minutes || "-" },
    { label: "Tdk absen plg", value: (r) => r.summary.no_clock_out || "-", warn: (r) => r.summary.no_clock_out > 0 },
    { label: "Tidak hadir", value: (r) => r.summary.absent || "-", warn: (r) => r.summary.absent > 0 },
    { label: "Cuti/sakit", value: (r) => r.summary.paid_leave || "-" },
    { label: "Izin tnp upah", value: (r) => r.summary.unpaid_leave || "-" },
    { label: "Lembur (jam)", value: (r) => hours(r.summary.overtime_minutes) },
    { label: "Lembur menunggu", value: (r) => hours(r.summary.overtime_pending_minutes), warn: (r) => r.summary.overtime_pending_minutes > 0 },
    { label: "Uang makan", value: (r) => r.summary.meal_days || "-" },
    { label: "Perlu tinjau", value: (r) => r.summary.review || "-", warn: (r) => r.summary.review > 0 },
  ];

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 6, gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Absensi</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14 }}>
            Rekap satu periode gaji. Klik sel untuk membuka hari itu dan memperbaikinya. Angka ringkasan sama dengan payroll.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button className="btn-ghost" disabled={!data} onClick={() => data && go(data.prev)} style={{ padding: "6px 8px" }} aria-label="Periode sebelumnya"><ChevronLeft size={16} /></button>
          <div style={{ minWidth: 190, textAlign: "center" }}>
            <div style={{ fontWeight: 800, color: "var(--midnight)" }}>{data ? `Periode ${data.label}` : "…"}</div>
            {data && <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{periodText(data.start, data.end)}</div>}
          </div>
          <button className="btn-ghost" disabled={!data} onClick={() => data && go(data.next)} style={{ padding: "6px 8px" }} aria-label="Periode berikutnya"><ChevronRight size={16} /></button>
          <button className="btn-ghost" disabled={!data || exporting} onClick={exportExcel}
                  style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 8 }}>
            {exporting ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Download size={15} />} Excel
          </button>
        </div>
      </div>

      <AbsensiTabs active="rekap" />

      {/* controls */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
        <div style={{ display: "inline-flex", border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}>
          {(["kode", "jam"] as const).map((v) => (
            <button key={v} onClick={() => setView(v)} style={{ padding: "6px 14px", fontSize: 13.5, fontWeight: 700, border: "none",
                    background: view === v ? "var(--midnight-soft)" : "transparent", color: view === v ? "var(--midnight)" : "var(--steel)" }}>
              {v === "kode" ? "Kode" : "Jam masuk/pulang"}
            </button>
          ))}
        </div>
        <input className="input" placeholder="Cari nama atau no. karyawan" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 240 }} />
        {sites.length > 0 && (
          <select className="input" value={site} onChange={(e) => { setSite(e.target.value); setPage(1); }} style={{ width: 170 }}>
            <option value="">Semua lokasi</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        )}
        {shifts.length > 1 && (
          <select className="input" value={shift} onChange={(e) => { setShift(e.target.value); setPage(1); }} style={{ width: 150 }}>
            <option value="">Semua shift</option>
            {shifts.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        )}
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13.5, cursor: "pointer" }}>
          <input type="checkbox" checked={problems} onChange={(e) => { setProblems(e.target.checked); setPage(1); }} />
          Hanya yang bermasalah
        </label>
        {data && <span style={{ marginLeft: "auto", fontSize: 13, color: "var(--steel)" }}>{data.total} karyawan</span>}
        {data && data.rows.length > 0 && (
          <button className="btn-ghost" onClick={jump} style={{ padding: "6px 12px", fontSize: 13.5 }}>
            {atSummary ? "← Tanggal" : "Ringkasan →"}
          </button>
        )}
      </div>

      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 14 }}>{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: open ? "minmax(0, 1fr) 440px" : "minmax(0, 1fr)", gap: 16, alignItems: "start" }}>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {loading && !data ? (
            <div style={{ padding: 24, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
          ) : !data || data.rows.length === 0 ? (
            <div style={{ padding: 24, color: "var(--steel)", fontSize: 14 }}>
              {problems ? "Tidak ada karyawan bermasalah di periode ini. Mantap!" : "Tidak ada karyawan di periode ini."}
            </div>
          ) : (
            <div ref={gridRef} onScroll={(e) => { const g = e.currentTarget; setAtSummary(g.scrollLeft + g.clientWidth >= g.scrollWidth - 40); }}
                 style={{ overflow: "auto", maxHeight: "calc(100vh - 260px)", opacity: loading ? 0.6 : 1 }}>
              <table style={{ borderCollapse: "separate", borderSpacing: 0, fontSize: 12.5 }}>
                <thead>
                  <tr>
                    <th style={{ ...th, left: 0, zIndex: 3, minWidth: NAME_W, textAlign: "left", paddingLeft: 10 }}>Karyawan</th>
                    {data.days.map((d) => (
                      <th key={d.d} style={{ ...th, minWidth: view === "jam" ? 46 : 30, background: d.sunday ? "#0B5574" : "var(--midnight)" }}>
                        {d.day}<div style={{ fontWeight: 500, opacity: 0.75, fontSize: 10.5 }}>{d.dow}</div>
                      </th>
                    ))}
                    {sumCols.map((s) => (
                      <th key={s.label} style={{ ...th, background: "#2A5F78", minWidth: 58, whiteSpace: "normal", lineHeight: 1.15 }}>{s.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.employee.id}>
                      <td style={{ position: "sticky", left: 0, background: "var(--card, #fff)", zIndex: 1, minWidth: NAME_W, maxWidth: NAME_W,
                                   padding: "5px 10px", borderBottom: "1px solid var(--line)", borderRight: "1px solid var(--line)" }}>
                        <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.employee.full_name}</div>
                        <div className="mono" style={{ fontSize: 11, color: "var(--steel)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                          {r.employee.employee_no}{r.employee.position ? ` · ${r.employee.position}` : ""}
                        </div>
                      </td>
                      {r.cells.map((c) => {
                        const st = CODE_STYLE[c.c] ?? { bg: "transparent", fg: "var(--steel)" };
                        const key = `${r.employee.id}-${c.d}`;
                        const clickable = c.c !== "-";
                        return (
                          <td key={c.d} title={cellTitle(r, c)}
                              onClick={() => clickable && setOpen({ row: toDayRow(r, c), key })}
                              style={{ position: "relative", textAlign: "center", padding: view === "jam" ? "3px 2px" : "5px 2px",
                                       background: st.bg, color: st.fg, fontWeight: 700, cursor: clickable ? "pointer" : "default",
                                       borderBottom: "1px solid var(--line)", borderRight: "1px solid rgba(0,0,0,0.04)",
                                       fontSize: view === "jam" ? 10.5 : 12.5, lineHeight: view === "jam" ? 1.25 : undefined,
                                       fontFamily: view === "jam" ? "var(--font-mono, monospace)" : undefined,
                                       outline: open?.key === key ? "2px solid var(--rust)" : undefined, outlineOffset: -2 }}>
                            {cellText(c)}
                            {c.hn && <NoteCorner color={c.hn.color} />}
                            {c.rv && <span style={{ position: "absolute", top: 1, right: 2, fontSize: 8, color: "var(--hazard-dark)" }}>●</span>}
                            {(c.ot > 0 || c.otp > 0) && (
                              <span style={{ position: "absolute", bottom: 0, right: 2, fontSize: 8.5, fontWeight: 800,
                                             color: c.ot ? "var(--workshop)" : "var(--hazard-dark)" }}>+</span>
                            )}
                          </td>
                        );
                      })}
                      {sumCols.map((s) => (
                        <td key={s.label} style={{ textAlign: "center", padding: "5px 4px", borderBottom: "1px solid var(--line)",
                                                   fontWeight: 600, color: s.warn?.(r) ? "var(--hazard-dark)" : undefined,
                                                   background: "var(--paper)" }}>{s.value(r)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data && data.pages > 1 && (
            <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, padding: 10, borderTop: "1px solid var(--line)" }}>
              <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
              <span style={{ fontSize: 13 }}>Hal. {data.page} / {data.pages}</span>
              <button className="btn-ghost" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>›</button>
            </div>
          )}
        </div>
        {open && (
          <DayPanel key={open.key} row={open.row} onChanged={() => load()} onClose={() => setOpen(null)} />
        )}
      </div>

      {/* legend */}
      {data && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 12, fontSize: 12.5, color: "var(--steel)" }}>
          {data.legend.map((l) => {
            const st = CODE_STYLE[l.code] ?? { bg: "transparent", fg: "var(--steel)" };
            return (
              <span key={l.code} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                <span style={{ background: st.bg, color: st.fg, fontWeight: 800, borderRadius: 4, padding: "1px 6px",
                               border: l.code === "-" ? "1px solid var(--line)" : undefined }}>{l.code}</span>{l.label}
              </span>
            );
          })}
          <span><span style={{ color: "var(--hazard-dark)" }}>●</span> perlu ditinjau</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span style={{ position: "relative", display: "inline-block", width: 14, height: 14, border: "1px solid var(--line)" }}>
              <NoteCorner color="00B0F0" /></span>
            ada catatan HR (warna dari file rekap)
          </span>
          <span><b style={{ color: "var(--workshop)" }}>+</b> lembur disetujui · <b style={{ color: "var(--hazard-dark)" }}>+</b> lembur menunggu</span>
        </div>
      )}
    </div>
  );
}
