"use client";
// =============================================================================
// /dashboard/lembur — approved overtime in rupiah for a month, PP 35/2021 (G4a).
// Per person (click to see every day's working), per site, PP 35 warnings,
// and a CSV download that opens in Excel.
// =============================================================================
import { minutesText } from "@/lib/api/attendance";
import { readErrors } from "@/lib/api/hr";
import { OvertimeMonth, OvertimePerson, overtimeApi } from "@/lib/api/overtime";
import { rupiah, todayISO } from "@/lib/format";
import { AlertTriangle, ChevronDown, ChevronRight, Download, Loader2 } from "lucide-react";
import Link from "next/link";
import { Fragment, useCallback, useEffect, useState } from "react";

const DAY_NAMES = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"];

function weekday(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return DAY_NAMES[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}

function toCsv(data: OvertimeMonth): string {
  const rows = [["No. karyawan", "Nama", "Tanggal", "Hari", "Jenis hari", "Lokasi", "Menit lembur", "Upah per jam", "Rincian", "Upah lembur (Rp)"]];
  for (const p of data.employees) {
    for (const d of p.days) {
      rows.push([p.employee.employee_no, p.employee.full_name, d.date, weekday(d.date), d.rest_day ? "Hari libur" : "Hari kerja",
                 d.site, String(d.minutes), d.hourly_rate ?? "", d.lines.map((l) => `${l.minutes} mnt x ${l.multiplier}`).join(" + "),
                 d.amount]);
    }
  }
  return rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\r\n");
}

export default function LemburPage() {
  const [month, setMonth] = useState(todayISO().slice(0, 7));
  const [data, setData] = useState<OvertimeMonth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async (m: string) => {
    setLoading(true);
    try { setData(await overtimeApi.month(m)); setError(null); }
    catch (err) { setError(readErrors(err).summary); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(month); }, [month, load]);

  const download = () => {
    if (!data) return;
    // Semicolons + a BOM: Excel with Indonesian settings opens it straight into columns.
    const blob = new Blob(["﻿" + toCsv(data)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `lembur-${data.month}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const warningsCount = (p: OvertimePerson) => p.warnings.length;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 14, gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Lembur</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14 }}>
            Lembur yang sudah disetujui HR, dihitung sesuai PP 35/2021. Usulan lembur menunggu di{" "}
            <Link href="/dashboard/absensi/tinjau" style={{ color: "var(--rust)" }}>Perlu Tinjau</Link>.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} style={{ width: 170 }} />
          <button className="btn-ghost" onClick={download} disabled={!data || data.employees.length === 0}
                  style={{ display: "flex", alignItems: "center", gap: 6 }}><Download size={15} /> CSV</button>
        </div>
      </div>

      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 14 }}>{error}</div>}
      {loading || !data ? (
        <div style={{ padding: 24, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
            {[["Total upah lembur", rupiah(data.totals.amount)], ["Total jam lembur", minutesText(data.totals.minutes)],
              ["Karyawan", String(data.totals.people)]].map(([label, value]) => (
              <div key={label} className="card" style={{ padding: "12px 16px", minWidth: 170 }}>
                <div style={{ fontSize: 22, fontWeight: 800 }}>{value}</div>
                <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{label}</div>
              </div>
            ))}
          </div>

          {data.employees.length === 0 ? (
            <div className="card" style={{ color: "var(--steel)", fontSize: 14 }}>Belum ada lembur yang disetujui untuk bulan ini.</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", gap: 18, alignItems: "start" }}>
              <div className="card" style={{ padding: 0 }}>
                <table className="data-table">
                  <thead><tr><th></th><th>Karyawan</th><th>Hari</th><th>Jam lembur</th><th>Upah/jam</th><th style={{ textAlign: "right" }}>Upah lembur</th></tr></thead>
                  <tbody>
                    {data.employees.map((p) => {
                      const isOpen = open === p.employee.id;
                      return (
                        <Fragment key={p.employee.id}>
                          <tr onClick={() => setOpen(isOpen ? null : p.employee.id)} style={{ cursor: "pointer" }}>
                            <td style={{ width: 24 }}>{isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
                            <td><div style={{ fontWeight: 600 }}>{p.employee.full_name}
                                {warningsCount(p) > 0 && <AlertTriangle size={14} style={{ color: "var(--hazard-dark)", marginLeft: 6, verticalAlign: "-2px" }} />}</div>
                              <div className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>{p.employee.employee_no}</div></td>
                            <td>{p.days.length}</td>
                            <td>{minutesText(p.minutes)}</td>
                            <td style={{ fontSize: 13 }}>{p.hourly_rate ? rupiah(p.hourly_rate) : "-"}</td>
                            <td style={{ textAlign: "right", fontWeight: 700 }}>{p.not_paid ? <span style={{ fontSize: 12.5, color: "var(--steel)", fontWeight: 400 }}>{p.not_paid}</span> : rupiah(p.amount)}</td>
                          </tr>
                          {isOpen && (
                            <tr><td colSpan={6} style={{ background: "var(--paper)", padding: "10px 16px" }}>
                              {p.warnings.map((w) => (
                                <div key={w} style={{ color: "var(--hazard-dark)", fontSize: 13, marginBottom: 4 }}>
                                  <AlertTriangle size={13} style={{ verticalAlign: "-2px" }} /> {w}
                                </div>
                              ))}
                              <table style={{ width: "100%", fontSize: 13 }}>
                                <tbody>
                                  {p.days.map((d) => (
                                    <tr key={d.day_id}>
                                      <td style={{ padding: "4px 0", whiteSpace: "nowrap" }} className="mono">{weekday(d.date)} {d.date}</td>
                                      <td>{d.rest_day ? <span className="pill soon">Hari libur</span> : "Hari kerja"}</td>
                                      <td>{d.site}</td>
                                      <td>{minutesText(d.minutes)}</td>
                                      <td style={{ color: "var(--steel)" }}>
                                        {d.lines.map((l) => `${minutesText(l.minutes)} × ${l.multiplier.replace(".", ",")}`).join(" + ")}
                                      </td>
                                      <td style={{ textAlign: "right", fontWeight: 600 }}>{rupiah(d.amount)}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </td></tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="card" style={{ padding: 16 }}>
                <div className="label" style={{ marginBottom: 8 }}>Per lokasi</div>
                {data.sites.map((s) => (
                  <div key={s.site} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 13.5 }}>
                    <div><div style={{ fontWeight: 600 }}>{s.site}</div><div style={{ color: "var(--steel)", fontSize: 12.5 }}>{minutesText(s.minutes)}</div></div>
                    <div style={{ fontWeight: 700 }}>{rupiah(s.amount)}</div>
                  </div>
                ))}
                <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 8 }}>Lembur dihitung di lokasi absen terakhir hari itu.</div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
