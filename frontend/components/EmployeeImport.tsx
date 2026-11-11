"use client";
// =============================================================================
// EmployeeImport — the "Import Excel" dialog on Karyawan (G9, 1 Nov 2026).
// 1. download the template  2. choose the filled file  3. preview (nothing saved yet)
// 4. "Simpan": new and changed employees are saved; rows with errors are left out.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { EmployeeImportResult, EmployeeImportRow, importApi } from "@/lib/api/imports";
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Loader2, X } from "lucide-react";
import { useState } from "react";

const ACTION: Record<EmployeeImportRow["action"], { label: string; bg: string; fg: string }> = {
  create: { label: "Baru", bg: "var(--workshop-lt)", fg: "var(--workshop)" },
  update: { label: "Diubah", bg: "var(--midnight-soft)", fg: "var(--midnight)" },
  same:   { label: "Sama", bg: "var(--paper-2)", fg: "var(--steel)" },
  error:  { label: "Salah", bg: "var(--danger-light)", fg: "var(--danger)" },
  skip:   { label: "Dilewati", bg: "var(--paper-2)", fg: "var(--steel)" },
};

export default function EmployeeImport({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<EmployeeImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState<"problems" | "all">("problems");

  const run = async (commit: boolean) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await importApi.employees(file, commit);
      setResult(r);
      if (commit) onDone();
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  const c = result?.counts;
  const toSave = c ? c.create + c.update : 0;
  const rows = result ? result.rows.filter((r) => show === "all" || r.action === "error" || r.warnings.length > 0 || r.action === "update" || r.action === "create" || r.action === "skip") : [];

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(1,61,90,0.45)", zIndex: 50, display: "flex", alignItems: "center",
                  justifyContent: "center", padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 860, maxWidth: "100%", maxHeight: "92vh", overflowY: "auto", padding: 22 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 19, fontWeight: 800, color: "var(--midnight)" }}>Import data karyawan</div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none" }}><X size={18} /></button>
        </div>
        <div style={{ fontSize: 13.5, color: "var(--steel)", margin: "4px 0 14px" }}>
          Gunakan template SeeGaji. Pratinjau dulu, baru simpan. Karyawan dicocokkan lewat No. Karyawan, jadi tidak ada yang dobel;
          sel kosong tidak menghapus data yang sudah ada.
        </div>

        {result?.applied ? (
          <div style={{ background: "var(--workshop-lt)", color: "var(--workshop)", borderRadius: 8, padding: "14px 16px", fontWeight: 700 }}>
            <CheckCircle2 size={16} style={{ verticalAlign: "-3px" }} /> Tersimpan: {result.applied.created} karyawan baru,
            {" "}{result.applied.updated} diperbarui.
            {c && c.error > 0 && <div style={{ fontWeight: 500, color: "var(--danger)", marginTop: 4 }}>{c.error} baris salah tidak disimpan; perbaiki di file lalu import lagi.</div>}
            <div style={{ marginTop: 10 }}><button className="btn-rust" onClick={onClose}>Selesai</button></div>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn-ghost" onClick={() => importApi.downloadTemplate().catch((err) => setError(readErrors(err).summary))}
                    style={{ display: "flex", alignItems: "center", gap: 6 }}><Download size={15} /> Unduh template</button>
            <label className="btn-ghost" style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <FileSpreadsheet size={15} /> {file ? file.name : "Pilih file (.xlsx / .csv)"}
              <input type="file" accept=".xlsx,.csv,.xls" style={{ display: "none" }}
                     onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null); }} />
            </label>
            <button className="btn-rust" disabled={!file || busy} onClick={() => run(false)}
                    style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />} Pratinjau
            </button>
          </div>
        )}

        {error && <div style={{ color: "var(--danger)", fontSize: 14, marginTop: 12 }}>{error}</div>}

        {result && c && (
          <div style={{ marginTop: 16 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              {(["create", "update", "same", "error", "skip"] as const).map((k) => (
                <span key={k} className="pill" style={{ background: ACTION[k].bg, color: ACTION[k].fg, fontSize: 13 }}>
                  {ACTION[k].label}: {c[k]}
                </span>
              ))}
            </div>
            {result.columns_missing.length > 0 && (
              <div style={{ color: "var(--hazard-dark)", fontSize: 13, marginBottom: 8 }}>
                <AlertTriangle size={13} style={{ verticalAlign: "-2px" }} /> Kolom wajib tidak ada di file: {result.columns_missing.join(", ")}.
                Karyawan baru tidak bisa dibuat tanpa kolom ini.
              </div>
            )}
            <div style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 8 }}>Kolom terbaca: {result.columns_found.join(", ")}</div>
            {(result.columns_ignored ?? []).length > 0 && (
              <div style={{ fontSize: 12.5, color: "var(--hazard-dark)", marginBottom: 8 }}>
                Kolom tidak dikenal (dilewati): {result.columns_ignored!.join(", ")}. Ganti judulnya seperti di template kalau isinya perlu.
              </div>
            )}
            {toSave === 0 && c.error === 0 && c.skip > 0 && (
              <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 8, padding: "10px 12px",
                            fontSize: 13.5, marginBottom: 10 }}>
                <AlertTriangle size={13} style={{ verticalAlign: "-2px" }} /> Semua baris dilewati. Lihat kolom Keterangan di bawah
                untuk alasannya.
              </div>
            )}

            <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
              {(["problems", "all"] as const).map((k) => (
                <button key={k} className="btn-ghost" onClick={() => setShow(k)}
                        style={{ padding: "4px 12px", fontSize: 13, background: show === k ? "var(--midnight-soft)" : undefined }}>
                  {k === "problems" ? "Baru, diubah & bermasalah" : "Semua baris"}
                </button>
              ))}
            </div>
            <div style={{ border: "1px solid var(--line)", borderRadius: 8, maxHeight: 360, overflowY: "auto" }}>
              <table className="data-table">
                <thead><tr><th>Baris</th><th>No. Karyawan</th><th>Nama</th><th>Hasil</th><th>Keterangan</th></tr></thead>
                <tbody>
                  {rows.length === 0 && <tr><td colSpan={5} style={{ color: "var(--steel)" }}>Tidak ada.</td></tr>}
                  {rows.map((r) => (
                    <tr key={r.row}>
                      <td className="mono">{r.row}</td>
                      <td className="mono">{r.employee_no || "-"}</td>
                      <td>{r.full_name || "-"}</td>
                      <td><span className="pill" style={{ background: ACTION[r.action].bg, color: ACTION[r.action].fg }}>{ACTION[r.action].label}</span></td>
                      <td style={{ fontSize: 13 }}>
                        {r.skip && <div style={{ color: "var(--steel)" }}>{r.skip}</div>}
                        {r.errors.map((e) => <div key={e} style={{ color: "var(--danger)" }}>{e}</div>)}
                        {r.warnings.map((w) => <div key={w} style={{ color: "var(--hazard-dark)" }}>{w}</div>)}
                        {r.changes.map((ch) => <div key={ch.field}>{ch.field}: <s style={{ color: "var(--steel)" }}>{ch.old}</s> → <b>{ch.new}</b></div>)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {!result.applied && (
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
                <button className="btn-ghost" onClick={onClose}>Batal</button>
                <button className="btn-rust" disabled={busy || toSave === 0} onClick={() => run(true)}>
                  {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
                  {toSave === 0 ? "Tidak ada yang perlu disimpan" : `Simpan ${toSave} karyawan`}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
