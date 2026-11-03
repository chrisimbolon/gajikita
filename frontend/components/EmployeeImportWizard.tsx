"use client";
// =============================================================================
// EmployeeImportWizard — "Import Excel" on Karyawan (G9d, 3 Nov 2026).
// Works with our template AND with the company's own file (old HRIS, payroll sheet, bank list):
//   1. choose the file: the sheet and the title row are found automatically
//   2. Kolom: every column with a few examples and what it is imported as; change any of them
//   3. Kata yang belum dikenali: their words ("Outsourcing", "BP Uban") mapped once for all rows
//   4. preview per row (paged), "Unduh baris yang salah" to fix only those, then Simpan
// The choices are remembered for the company, so next month's file imports in one click.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { EmployeeImportOptions, EmployeeImportResult, EmployeeImportRow, importApi } from "@/lib/api/imports";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Download, FileSpreadsheet, Loader2, RotateCcw, X } from "lucide-react";
import { useState } from "react";

const ACTION: Record<EmployeeImportRow["action"], { label: string; bg: string; fg: string }> = {
  create: { label: "Baru", bg: "var(--workshop-lt)", fg: "var(--workshop)" },
  update: { label: "Diubah", bg: "var(--midnight-soft)", fg: "var(--midnight)" },
  same:   { label: "Sama", bg: "var(--paper-2)", fg: "var(--steel)" },
  error:  { label: "Salah", bg: "var(--danger-light)", fg: "var(--danger)" },
  skip:   { label: "Dilewati", bg: "var(--paper-2)", fg: "var(--steel)" },
};
const PAGE = 100;
const EMPTY = "__empty__";

export default function EmployeeImportWizard({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<EmployeeImportResult | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [sheet, setSheet] = useState<string | undefined>(undefined);
  const [reset, setReset] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState<"problems" | "all">("problems");
  const [page, setPage] = useState(1);
  const [columnsOpen, setColumnsOpen] = useState<boolean | null>(null);

  const opts = (o: Partial<EmployeeImportOptions> = {}): EmployeeImportOptions =>
    ({ mapping, values, sheet, reset, ...o });

  const run = async (commit: boolean, o: Partial<EmployeeImportOptions> = {}) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await importApi.employeesMapped(file, commit, opts(o));
      setResult(r);
      setPage(1);
      if (commit) onDone();
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  const pick = (f: File | null) => {
    setFile(f); setResult(null); setError(null); setMapping({}); setValues({}); setSheet(undefined); setReset(false);
    setColumnsOpen(null);
  };

  const chooseColumn = (key: string, field: string) => {
    // a field belongs to one column: choosing it here takes it away from any other column
    const next: Record<string, string> = { ...mapping, [key]: field };
    if (field !== "-") {
      for (const c of result?.columns ?? []) {
        if (c.key !== key && (next[c.key] ?? (c.field || "-")) === field) next[c.key] = "-";
      }
    }
    setMapping(next);
    run(false, { mapping: next });
  };

  const chooseWord = (field: string, key: string, value: string) => {
    const next = { ...values, [field]: { ...(values[field] ?? {}), [key]: value === EMPTY ? "" : value } };
    setValues(next);
    run(false, { values: next });
  };

  const startOver = () => {
    setMapping({}); setValues({}); setReset(true);
    run(false, { mapping: {}, values: {}, reset: true });
  };

  const c = result?.counts;
  const toSave = c ? c.create + c.update : 0;
  const rows = result ? result.rows.filter((r) => show === "all" || r.action !== "same") : [];
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice((page - 1) * PAGE, page * PAGE);
  const columns = result?.columns ?? [];
  const unknown = result?.unknown_values ?? [];
  const openColumns = columnsOpen ?? !!(result && (result.needs_mapping || result.columns_missing.length > 0));

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(1,61,90,0.45)", zIndex: 50, display: "flex", alignItems: "center",
                  justifyContent: "center", padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 940, maxWidth: "100%", maxHeight: "94vh", overflowY: "auto", padding: 22 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 19, fontWeight: 800, color: "var(--midnight)" }}>Import data karyawan</div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none" }}><X size={18} /></button>
        </div>
        <div style={{ fontSize: 13.5, color: "var(--steel)", margin: "4px 0 14px" }}>
          Pakai template kami, <b>atau file karyawan yang sudah Anda punya</b> (dari HRIS lama, Excel payroll, daftar bank).
          Kolom dikenali otomatis; yang belum, pilih sekali dan akan diingat untuk import berikutnya. Karyawan dicocokkan lewat
          No. Karyawan, sel kosong tidak menghapus data. Bisa bertahap: import dulu data gaji, lalu file BPJS atau rekening menyusul.
        </div>

        {result?.applied ? (
          <div style={{ background: "var(--workshop-lt)", color: "var(--workshop)", borderRadius: 8, padding: "14px 16px", fontWeight: 700 }}>
            <CheckCircle2 size={16} style={{ verticalAlign: "-3px" }} /> Tersimpan: {result.applied.created} karyawan baru,
            {" "}{result.applied.updated} diperbarui. Pilihan kolom diingat untuk import berikutnya.
            {c && c.error > 0 && (
              <div style={{ fontWeight: 500, color: "var(--danger)", marginTop: 4 }}>
                {c.error} baris salah tidak disimpan.{" "}
                <button className="btn-ghost" style={{ padding: "2px 10px", fontSize: 13 }}
                        onClick={() => file && importApi.downloadErrorRows(file, opts()).catch((err) => setError(readErrors(err).summary))}>
                  Unduh baris yang salah
                </button>
              </div>
            )}
            <div style={{ marginTop: 10 }}><button className="btn-rust" onClick={onClose}>Selesai</button></div>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn-ghost" onClick={() => importApi.downloadTemplate().catch((err) => setError(readErrors(err).summary))}
                    style={{ display: "flex", alignItems: "center", gap: 6 }}><Download size={15} /> Unduh template</button>
            <label className="btn-ghost" style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <FileSpreadsheet size={15} /> {file ? file.name : "Pilih file (.xlsx / .csv)"}
              <input type="file" accept=".xlsx,.csv,.xls" style={{ display: "none" }} onChange={(e) => pick(e.target.files?.[0] ?? null)} />
            </label>
            <button className="btn-rust" disabled={!file || busy} onClick={() => run(false)} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />} Pratinjau
            </button>
          </div>
        )}

        {error && <div style={{ color: "var(--danger)", fontSize: 14, marginTop: 12 }}>{error}</div>}

        {result && c && !result.applied && (
          <div style={{ marginTop: 16, opacity: busy ? 0.6 : 1 }}>
            {/* where we read from */}
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", fontSize: 13.5, marginBottom: 10 }}>
              {(result.sheets ?? []).length > 1 ? (
                <label style={{ display: "flex", alignItems: "center", gap: 6 }}>Sheet
                  <select className="input" value={result.sheet} style={{ width: 200, padding: "4px 8px" }}
                          onChange={(e) => { setSheet(e.target.value); setMapping({}); setValues({}); run(false, { sheet: e.target.value, mapping: {}, values: {} }); }}>
                    {result.sheets!.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </label>
              ) : result.sheet ? <span>Sheet <b>{result.sheet}</b></span> : null}
              {result.header_row && <span style={{ color: "var(--steel)" }}>· judul kolom di baris {result.header_row}</span>}
              {result.profile_used && (
                <span className="pill" style={{ background: "var(--midnight-soft)", color: "var(--midnight)", fontSize: 12.5 }}>
                  Memakai pilihan kolom dari import sebelumnya
                </span>
              )}
              {(result.profile_used || Object.keys(mapping).length > 0) && (
                <button className="btn-ghost" onClick={startOver} style={{ padding: "3px 10px", fontSize: 12.5, display: "flex", alignItems: "center", gap: 4 }}>
                  <RotateCcw size={12} /> Atur ulang pilihan
                </button>
              )}
            </div>

            {(result.needs_mapping || result.columns_missing.length > 0) && (
              <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 8, padding: "10px 12px", fontSize: 13.5, marginBottom: 10 }}>
                <AlertTriangle size={13} style={{ verticalAlign: "-2px" }} />{" "}
                {result.needs_mapping ? result.message
                  : <>Belum ada kolom untuk: <b>{result.columns_missing.join(", ")}</b>. Karyawan baru butuh kolom ini; pilih di daftar kolom
                     di bawah kalau ada di file dengan judul lain.</>}
              </div>
            )}

            {/* 2. columns */}
            <div style={{ border: "1px solid var(--line)", borderRadius: 8, marginBottom: 12 }}>
              <button onClick={() => setColumnsOpen(!openColumns)}
                      style={{ width: "100%", display: "flex", alignItems: "center", gap: 6, background: "none", border: "none", padding: "10px 12px",
                               fontWeight: 700, fontSize: 14, color: "var(--midnight)", cursor: "pointer", textAlign: "left" }}>
                {openColumns ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                Kolom: {columns.filter((x) => x.field).length} diimport, {columns.filter((x) => !x.field).length} dilewati
                <span style={{ fontWeight: 500, color: "var(--steel)", marginLeft: 6 }}>{openColumns ? "" : "· lihat / ubah"}</span>
              </button>
              {openColumns && (
                <div style={{ maxHeight: 320, overflowY: "auto", borderTop: "1px solid var(--line)" }}>
                  <table className="data-table">
                    <thead><tr><th>Kolom di file</th><th>Contoh isi</th><th style={{ width: 280 }}>Diimport sebagai</th></tr></thead>
                    <tbody>
                      {columns.map((col) => {
                        const current = mapping[col.key] ?? (col.field || "-");
                        return (
                          <tr key={col.index}>
                            <td style={{ fontWeight: 600 }}>{col.title}</td>
                            <td style={{ fontSize: 12.5, color: "var(--steel)" }}>{col.sample.join(" · ") || "-"}</td>
                            <td>
                              <select className="input" value={current} disabled={busy} aria-label={`Kolom ${col.title}`}
                                      onChange={(e) => chooseColumn(col.key, e.target.value)}
                                      style={{ padding: "4px 8px", fontSize: 13, color: current === "-" ? "var(--steel)" : undefined }}>
                                <option value="-">— Tidak diimport —</option>
                                {(result.fields ?? []).map((f) => (
                                  <option key={f.field} value={f.field}>{f.label}{f.required ? " *" : ""}</option>
                                ))}
                              </select>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <div style={{ fontSize: 12, color: "var(--steel)", padding: "6px 12px" }}>* wajib untuk karyawan baru</div>
                </div>
              )}
            </div>

            {/* 3. words we could not read */}
            {unknown.length > 0 && (
              <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "10px 12px", marginBottom: 12 }}>
                <div style={{ fontWeight: 700, fontSize: 14, color: "var(--midnight)", marginBottom: 6 }}>
                  Isi yang belum dikenali <span style={{ fontWeight: 500, color: "var(--steel)" }}>· pilih sekali, berlaku untuk semua baris</span>
                </div>
                <div style={{ display: "grid", gap: 6 }}>
                  {unknown.map((u) => {
                    const chosen = u.mapped === "" ? EMPTY : (u.mapped ?? "");
                    return (
                      <div key={`${u.field}-${u.key}`} style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", fontSize: 13.5 }}>
                        <span style={{ minWidth: 260 }}>
                          <span style={{ color: "var(--steel)" }}>{u.label}:</span> <b>&ldquo;{u.raw}&rdquo;</b>
                          <span style={{ color: "var(--steel)" }}> · {u.count} baris</span>
                        </span>
                        {u.options.length === 0 ? (
                          <span style={{ color: "var(--hazard-dark)", fontSize: 13 }}>
                            Belum ada {u.field === "shift" ? "shift" : "lokasi"} di sistem; buat dulu di menu {u.field === "shift" ? "Shift" : "Lokasi"}, lalu pratinjau lagi.
                          </span>
                        ) : (
                          <select className="input" value={chosen} disabled={busy} aria-label={`${u.label} ${u.raw}`}
                                  onChange={(e) => e.target.value && chooseWord(u.field, u.key, e.target.value)}
                                  style={{ width: 240, padding: "4px 8px", fontSize: 13,
                                           borderColor: chosen ? undefined : "var(--hazard)" }}>
                            <option value="">Pilih…</option>
                            {u.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                            <option value={EMPTY}>(kosongkan)</option>
                          </select>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 4. rows */}
            {!result.needs_mapping && (
              <>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
                  {(["create", "update", "same", "error", "skip"] as const).map((k) => (
                    <span key={k} className="pill" style={{ background: ACTION[k].bg, color: ACTION[k].fg, fontSize: 13 }}>{ACTION[k].label}: {c[k]}</span>
                  ))}
                  {c.error > 0 && (
                    <button className="btn-ghost" disabled={busy} style={{ marginLeft: "auto", padding: "4px 12px", fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}
                            onClick={() => file && importApi.downloadErrorRows(file, opts()).catch((err) => setError(readErrors(err).summary))}>
                      <Download size={13} /> Unduh {c.error} baris yang salah
                    </button>
                  )}
                </div>
                {toSave === 0 && c.error === 0 && c.skip > 0 && (
                  <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 8, padding: "10px 12px", fontSize: 13.5, marginBottom: 10 }}>
                    <AlertTriangle size={13} style={{ verticalAlign: "-2px" }} /> Semua baris dilewati. Lihat kolom Keterangan untuk alasannya.
                  </div>
                )}
                <div style={{ display: "flex", gap: 6, marginBottom: 8, alignItems: "center" }}>
                  {(["problems", "all"] as const).map((k) => (
                    <button key={k} className="btn-ghost" onClick={() => { setShow(k); setPage(1); }}
                            style={{ padding: "4px 12px", fontSize: 13, background: show === k ? "var(--midnight-soft)" : undefined }}>
                      {k === "problems" ? "Baru, diubah & bermasalah" : "Semua baris"}
                    </button>
                  ))}
                  {pages > 1 && (
                    <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
                      <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)} style={{ padding: "2px 10px" }}>‹</button>
                      Hal. {page} / {pages}
                      <button className="btn-ghost" disabled={page >= pages} onClick={() => setPage(page + 1)} style={{ padding: "2px 10px" }}>›</button>
                    </span>
                  )}
                </div>
                <div style={{ border: "1px solid var(--line)", borderRadius: 8, maxHeight: 360, overflowY: "auto" }}>
                  <table className="data-table">
                    <thead><tr><th>Baris</th><th>No. Karyawan</th><th>Nama</th><th>Hasil</th><th>Keterangan</th></tr></thead>
                    <tbody>
                      {shown.length === 0 && <tr><td colSpan={5} style={{ color: "var(--steel)" }}>Tidak ada.</td></tr>}
                      {shown.map((r) => (
                        <tr key={r.row}>
                          <td className="mono">{r.row}</td>
                          <td className="mono">{r.employee_no || "-"}</td>
                          <td>{r.full_name || "-"}</td>
                          <td><span className="pill" style={{ background: ACTION[r.action].bg, color: ACTION[r.action].fg }}>{ACTION[r.action].label}</span></td>
                          <td style={{ fontSize: 13 }}>
                            {r.skip && <div style={{ color: "var(--steel)" }}>{r.skip}</div>}
                            {r.errors.map((e) => <div key={e} style={{ color: "var(--danger)" }}>{e}</div>)}
                            {r.warnings.map((w) => <div key={w} style={{ color: "var(--hazard-dark)" }}>{w}</div>)}
                            {r.changes.map((ch) => (
                              <div key={ch.field}>{ch.field}:{" "}
                                {ch.old === "-" ? <span style={{ color: "var(--steel)" }}>(kosong)</span>
                                  : <s style={{ color: "var(--steel)" }}>{ch.old}</s>} → <b>{ch.new === "-" ? "(kosong)" : ch.new}</b>
                              </div>
                            ))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
                  <button className="btn-ghost" onClick={onClose}>Batal</button>
                  <button className="btn-rust" disabled={busy || toSave === 0} onClick={() => run(true)}>
                    {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
                    {toSave === 0 ? "Tidak ada yang perlu disimpan" : `Simpan ${toSave} karyawan`}
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
