"use client";
// =============================================================================
// /dashboard/absensi — the daily attendance page (G3, 28 Oct 2026).
// Pick a date; the counters across the top are filters (Talenta idea);
// click a person to open their day.
// =============================================================================
import DayPanel, { StatusPill } from "@/components/DayPanel";
import { Counter, DayRow, attendanceApi, minutesText } from "@/lib/api/attendance";
import { readErrors } from "@/lib/api/hr";
import { todayISO } from "@/lib/format";
import FingerprintImport from "@/components/FingerprintImport";
import AbsensiTabs from "@/components/AbsensiTabs";
import { ChevronLeft, ChevronRight, Fingerprint, Loader2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

function shiftDate(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}-${String(dt.getUTCDate()).padStart(2, "0")}`;
}

export default function AbsensiPage() {
  const [date, setDate] = useState(todayISO());
  const [rows, setRows] = useState<DayRow[]>([]);
  const [counters, setCounters] = useState<Counter[]>([]);
  const [filter, setFilter] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<DayRow | null>(null);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async (d: string) => {
    setLoading(true);
    try {
      const data = await attendanceApi.daily(d);
      setRows(data.rows); setCounters(data.counters); setError(null);
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(date); setOpen(null); }, [date, load]);

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return rows.filter((r) =>
      (!filter || (filter === "needs_review" ? r.needs_review : r.tags.includes(filter as DayRow["status"])))
      && (!t || r.employee.full_name.toLowerCase().includes(t) || r.employee.employee_no.toLowerCase().includes(t)));
  }, [rows, filter, q]);

  const onChanged = () => { load(date); };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 14, gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Absensi</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14 }}>Status setiap karyawan per hari. Klik angka untuk menyaring.</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button className="btn-ghost" onClick={() => setImporting(true)}
                  style={{ display: "flex", alignItems: "center", gap: 6, marginRight: 8 }}>
            <Fingerprint size={15} /> Import fingerprint
          </button>
          <button className="btn-ghost" onClick={() => setDate(shiftDate(date, -1))} style={{ padding: "6px 8px" }} aria-label="Hari sebelumnya"><ChevronLeft size={16} /></button>
          <input className="input" type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} style={{ width: 160 }} />
          <button className="btn-ghost" onClick={() => setDate(shiftDate(date, 1))} style={{ padding: "6px 8px" }} aria-label="Hari berikutnya"><ChevronRight size={16} /></button>
          {date !== todayISO() && <button className="btn-ghost" onClick={() => setDate(todayISO())} style={{ padding: "6px 12px", fontSize: 13 }}>Hari ini</button>}
        </div>
      </div>

      <AbsensiTabs active="harian" />

      {importing && <FingerprintImport onClose={() => setImporting(false)} onDone={() => load(date)} />}

      {/* counters = filters */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
        {counters.filter((c) => c.count > 0 || ["on_time", "late", "absent", "needs_review"].includes(c.key)).map((c) => {
          const active = filter === c.key;
          const review = c.key === "needs_review";
          return (
            <button key={c.key} onClick={() => setFilter(active ? null : c.key)} className="card"
                    style={{ padding: "10px 14px", minWidth: 110, textAlign: "left", cursor: "pointer",
                             borderColor: active ? "var(--rust)" : review && c.count ? "var(--hazard)" : undefined,
                             background: active ? "var(--rust-light)" : undefined }}>
              <div style={{ fontSize: 22, fontWeight: 800 }}>{c.count}</div>
              <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{c.label}</div>
            </button>
          );
        })}
        <Link href="/dashboard/absensi/tinjau" style={{ alignSelf: "center", marginLeft: "auto", color: "var(--rust)", fontWeight: 600, fontSize: 14 }}>
          Antrean tinjau →
        </Link>
      </div>

      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 14 }}>{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: open ? "minmax(0, 1fr) 460px" : "1fr", gap: 18, alignItems: "start" }}>
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: 12, borderBottom: "1px solid var(--line)" }}>
            <input className="input" style={{ border: "none", background: "transparent" }} placeholder="Cari nama atau no. karyawan"
                   value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {loading ? (
            <div style={{ padding: 24, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
          ) : shown.length === 0 ? (
            <div style={{ padding: 24, color: "var(--steel)", fontSize: 14 }}>{rows.length ? "Tidak ada yang cocok." : "Belum ada karyawan aktif pada tanggal ini."}</div>
          ) : (
            <table className="data-table">
              <thead><tr><th>Karyawan</th><th>Status</th><th>Masuk</th><th>Pulang</th>{!open && <th>Jam kerja</th>}{!open && <th>Catatan</th>}</tr></thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.employee.id} onClick={() => setOpen(r)} style={{ cursor: "pointer",
                      background: open?.employee.id === r.employee.id ? "var(--paper)" : undefined }}>
                    <td><div style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{r.employee.full_name}</div>
                      <div className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>{r.employee.employee_no}</div></td>
                    <td><StatusPill status={r.status} label={r.status_label} />
                      {r.needs_review && <span title="Perlu ditinjau" style={{ color: "var(--hazard-dark)", marginLeft: 6 }}>●</span>}</td>
                    <td className="mono" style={{ fontSize: 13.5 }}>{r.first_in ?? "-"}</td>
                    <td className="mono" style={{ fontSize: 13.5 }}>{r.last_out ?? "-"}</td>
                    {!open && <td style={{ fontSize: 13 }}>{r.worked_minutes ? minutesText(r.worked_minutes) : "-"}</td>}
                    {!open && <td style={{ fontSize: 12.5, color: "var(--steel)" }}>{r.review_reasons.join(" · ")}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {open && <DayPanel key={`${open.employee.id}-${open.date}`} row={open} onChanged={onChanged} onClose={() => setOpen(null)} />}
      </div>
    </div>
  );
}
