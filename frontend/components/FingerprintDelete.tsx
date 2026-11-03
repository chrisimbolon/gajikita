"use client";
// =============================================================================
// FingerprintDelete — "Hapus data import" (G9b, 2 Nov 2026). Opened from the
// "Import fingerprint" dialog on Absensi.
// 1. pick the dates  2. preview (nothing removed yet)  3. write a reason  4. Hapus.
// Only taps from the machine go; phone taps, leave and locked payroll days stay.
// Days HR already decided are kept unless HR unticks the box.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { FingerprintDeleteResult, importApi } from "@/lib/api/imports";
import { todayISO } from "@/lib/format";
import { AlertTriangle, ArrowLeft, CheckCircle2, Loader2, Trash2, X } from "lucide-react";
import { useState } from "react";

function minusDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d - n));
  return `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}-${String(dt.getUTCDate()).padStart(2, "0")}`;
}

function d(iso: string) {
  const [y, m, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("id-ID", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" })
    .format(new Date(Date.UTC(y, m - 1, day)));
}

export default function FingerprintDelete({ period, onBack, onClose, onDone }: {
  period?: { start: string; end: string } | null; onBack: () => void; onClose: () => void; onDone: () => void;
}) {
  const [start, setStart] = useState(period?.start ?? minusDays(todayISO(), 30));
  const [end, setEnd] = useState(period?.end ?? todayISO());
  const [keepDecided, setKeepDecided] = useState(true);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<FingerprintDeleteResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (commit: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await importApi.deleteFingerprint({ start, end, keep_decided: keepDecided, commit, reason });
      setResult(r);
      if (commit) onDone();
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  const changed = () => { setResult(null); setError(null); };
  const t = result?.totals;

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(1,61,90,0.45)", zIndex: 50, display: "flex", alignItems: "center",
                  justifyContent: "center", padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 760, maxWidth: "100%", maxHeight: "92vh", overflowY: "auto", padding: 22 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 19, fontWeight: 800, color: "var(--midnight)" }}>Hapus data import fingerprint</div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none" }}><X size={18} /></button>
        </div>
        <button onClick={onBack} style={{ background: "none", border: "none", color: "var(--rust)", fontWeight: 600, fontSize: 13.5,
                                          padding: 0, margin: "2px 0 8px", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
          <ArrowLeft size={14} /> Kembali ke import
        </button>
        <div style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 14 }}>
          Untuk file yang salah: hapus tap dari mesin di tanggal ini, lalu import file yang benar. Hanya tap <b>mesin fingerprint</b> yang
          dihapus; absen lewat HP, cuti dan hari yang sudah masuk payroll terkunci tidak disentuh.
        </div>

        {result?.applied ? (
          <div style={{ background: "var(--workshop-lt)", color: "var(--workshop)", borderRadius: 8, padding: "14px 16px", fontWeight: 700 }}>
            <CheckCircle2 size={16} style={{ verticalAlign: "-3px" }} /> Terhapus: {result.applied.taps} tap di {result.applied.days} hari kerja.
            <div style={{ fontWeight: 500, color: "var(--ink)", marginTop: 4, fontSize: 13.5 }}>
              Sekarang file yang benar bisa diimport lagi.
              {result.draft_runs.length > 0 && <> Hitung ulang <b>{result.draft_runs.join(", ")}</b> setelah import.</>}
            </div>
            <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
              <button className="btn-rust" onClick={onBack}>Import file yang benar</button>
              <button className="btn-ghost" onClick={onClose}>Selesai</button>
            </div>
          </div>
        ) : (
          <>
            <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div><label className="label">Dari tanggal</label>
                <input className="input" type="date" value={start} onChange={(e) => { setStart(e.target.value); changed(); }} style={{ width: 160 }} /></div>
              <div><label className="label">Sampai tanggal</label>
                <input className="input" type="date" value={end} onChange={(e) => { setEnd(e.target.value); changed(); }} style={{ width: 160 }} /></div>
              <button className="btn-ghost" disabled={busy || !start || !end} onClick={() => run(false)}
                      style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {busy && !result && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />} Pratinjau
              </button>
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13.5, marginTop: 10, cursor: "pointer" }}>
              <input type="checkbox" checked={keepDecided} onChange={(e) => { setKeepDecided(e.target.checked); changed(); }} />
              Pertahankan hari yang sudah diputuskan / dikoreksi HR
            </label>
          </>
        )}

        {error && <div style={{ color: "var(--danger)", fontSize: 14, marginTop: 12 }}>{error}</div>}

        {result && t && !result.applied && (
          <div style={{ marginTop: 16 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
              <span className="pill" style={{ background: "var(--danger-light)", color: "var(--danger)", fontSize: 13 }}>
                Akan dihapus: {t.taps} tap · {t.days} hari · {t.people} karyawan</span>
              {t.locked_days > 0 && <span className="pill" style={{ background: "var(--paper-2)", color: "var(--steel)", fontSize: 13 }}>
                {t.locked_days} hari terkunci (payroll), dilewati</span>}
              {t.decided_kept > 0 && <span className="pill" style={{ background: "var(--midnight-soft)", color: "var(--midnight)", fontSize: 13 }}>
                {t.decided_kept} hari keputusan HR dipertahankan</span>}
              {t.decided_removed > 0 && <span className="pill" style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", fontSize: 13 }}>
                {t.decided_removed} hari keputusan HR ikut dihapus</span>}
            </div>

            {result.locked_runs.length > 0 && (
              <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 8 }}>
                {result.locked_runs.join(", ")} sudah dikunci. Untuk menghapus hari-hari itu, buka kembali payroll-nya dulu.
              </div>
            )}
            {result.decided.length > 0 && (
              <div style={{ background: "var(--hazard-light)", borderRadius: 8, padding: "10px 12px", marginBottom: 12, fontSize: 13 }}>
                <div style={{ fontWeight: 700, color: "var(--hazard-dark)", marginBottom: 4 }}>
                  <AlertTriangle size={13} style={{ verticalAlign: "-2px" }} /> Hari yang sudah dikerjakan HR
                  {keepDecided ? " (dipertahankan):" : " (keputusannya ikut dihapus):"}
                </div>
                {result.decided.map((x) => (
                  <div key={`${x.employee_no}-${x.date}`}>{x.full_name} · {d(x.date)} · {x.what.join(", ")}</div>
                ))}
              </div>
            )}

            {result.people.length > 0 && (
              <div style={{ border: "1px solid var(--line)", borderRadius: 8, maxHeight: 240, overflowY: "auto", marginBottom: 12 }}>
                <table className="data-table">
                  <thead><tr><th>Karyawan</th><th>Hari</th><th>Tap</th></tr></thead>
                  <tbody>
                    {result.people.map((p) => (
                      <tr key={p.employee.id}>
                        <td><div style={{ fontWeight: 600 }}>{p.employee.full_name}</div>
                          <div className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>{p.employee.employee_no}</div></td>
                        <td>{p.days}</td><td>{p.taps}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {t.taps === 0 ? (
              <div style={{ fontSize: 14, color: "var(--steel)" }}>Tidak ada tap fingerprint yang bisa dihapus di tanggal ini.</div>
            ) : (
              <>
                <label className="label">Alasan (wajib, masuk ke log audit)</label>
                <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="mis. file mesin salah, import ulang" />
                <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
                  <button className="btn-ghost" onClick={onClose}>Batal</button>
                  <button className="btn-rust" disabled={busy || reason.trim().length < 5} onClick={() => run(true)}
                          style={{ display: "flex", alignItems: "center", gap: 6, background: "var(--danger)" }}>
                    {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Trash2 size={15} />}
                    Hapus {t.taps} tap
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
