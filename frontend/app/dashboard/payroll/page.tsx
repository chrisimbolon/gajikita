"use client";
// =============================================================================
// /dashboard/payroll — the list of pay runs (G8b part 1, 1 Nov 2026).
// Create the run for a month (the period that ENDS that month, e.g. 26 Sep - 25 Oct
// for October), open it, or go to the payroll settings.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { RunSummary, dayLabel, payrollApi, periodLabel } from "@/lib/api/payroll";
import { rupiah, todayISO } from "@/lib/format";
import { AlertTriangle, Loader2, Lock, Plus, Settings } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

export default function PayrollPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [month, setMonth] = useState(todayISO().slice(0, 7));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    payrollApi.runs().then(setRuns).catch((err) => setError(readErrors(err).summary));
  }, []);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const run = await payrollApi.createRun(month);
      window.location.href = `/dashboard/payroll/run?id=${run.id}`;
    } catch (err) {
      setError(readErrors(err).summary);
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: 1100 }}>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Payroll</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14, maxWidth: 620 }}>
            Gaji dihitung dari absensi, lembur yang disetujui, cuti dan izin. Tambahkan insentif, kasbon atau potongan
            lain, periksa peringatan, lalu kunci.
          </p>
        </div>
        <Link href="/dashboard/payroll/pengaturan" className="btn-ghost"
              style={{ display: "flex", alignItems: "center", gap: 6, textDecoration: "none" }}>
          <Settings size={15} /> Pengaturan payroll
        </Link>
      </div>

      <div className="card" style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <div style={{ fontWeight: 700, color: "var(--midnight)" }}>Buat payroll bulan</div>
        <input className="input" type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} style={{ width: 170 }} />
        <button className="btn-rust" onClick={create} disabled={busy} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={15} />} Buat & hitung
        </button>
        <div style={{ fontSize: 13, color: "var(--steel)" }}>Periode mengikuti pengaturan (misalnya 26 bulan lalu s/d 25 bulan ini).</div>
      </div>

      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 14 }}>{error}</div>}

      {!runs ? (
        <div style={{ padding: 24, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
      ) : runs.length === 0 ? (
        <div className="card" style={{ color: "var(--steel)", fontSize: 14 }}>
          Belum ada payroll. Cek dulu <Link href="/dashboard/payroll/pengaturan" style={{ color: "var(--rust)" }}>pengaturan payroll</Link>,
          lalu buat payroll pertama di atas.
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table className="data-table">
            <thead><tr><th>Payroll</th><th>Periode</th><th>Gajian</th><th>Karyawan</th><th style={{ textAlign: "right" }}>Total bersih</th><th>Status</th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} onClick={() => { window.location.href = `/dashboard/payroll/run?id=${r.id}`; }} style={{ cursor: "pointer" }}>
                  <td style={{ fontWeight: 700 }}>{r.name}</td>
                  <td>{periodLabel(r.period_start, r.period_end)}</td>
                  <td>{r.pay_date ? dayLabel(r.pay_date) : "-"}</td>
                  <td>{r.people}</td>
                  <td style={{ textAlign: "right", fontWeight: 700 }}>{rupiah(r.net)}</td>
                  <td>
                    {r.status === "locked"
                      ? <span className="pill" style={{ background: "var(--workshop-lt)", color: "var(--workshop)" }}><Lock size={12} /> Dikunci</span>
                      : <span className="pill" style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)" }}>Draft</span>}
                    {r.warnings > 0 && (
                      <span style={{ marginLeft: 8, fontSize: 12.5, color: "var(--hazard-dark)" }}>
                        <AlertTriangle size={12} style={{ verticalAlign: "-1px" }} /> {r.warnings}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
