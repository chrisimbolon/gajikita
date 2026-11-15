"use client";
// =============================================================================
// /dashboard/payroll/run/item?id=... — manual items for everyone, in one table (G13 part 1, 15 Nov 2026).
// One row per employee, one column per item (Insentif BPJS Kesehatan, Kubikasi, Pinjaman / kasbon ...).
// Type or paste a column straight from Excel (a pasted list fills down, tabs fill right), tick "tiap bulan"
// for items that repeat (copied into next month's run), then "Simpan". Only the changed people are recalculated.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { GridColumn, ItemGrid, payrollApi } from "@/lib/api/payroll";
import { rupiah } from "@/lib/format";
import { ArrowLeft, Loader2, Lock, Plus, Save, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type ClipboardEvent } from "react";

const LOAN = "__loan_balance";                      // the "Sisa pinjaman" column (on the slip, not an item)

/** "35000.00" -> "35.000"; "" stays "". */
function show(v: string | null | undefined): string {
  if (v == null || v === "") return "";
  const n = Number(v);
  return Number.isFinite(n) && n !== 0 ? new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(n) : "";
}
/** what HR typed -> digits only ("Rp 35.000" -> "35000"); "" = empty. */
function clean(text: string): string {
  return text.replace(/[^\d]/g, "");
}
const key = (line: string, code: string) => `${line}|${code}`;

export default function ItemGridPage() {
  const [id, setId] = useState<string | null>(null);
  const [data, setData] = useState<ItemGrid | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});          // key -> digits ("" = remove)
  const [extra, setExtra] = useState<GridColumn[]>([]);                     // columns added here, not saved yet
  const [recurring, setRecurring] = useState<Record<string, boolean>>({});  // code -> tiap bulan (changed)
  const [adding, setAdding] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newKind, setNewKind] = useState<"earning" | "deduction">("earning");
  const [showLoan, setShowLoan] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const load = useCallback(async (runId: string) => {
    try {
      const g = await payrollApi.itemGrid(runId);
      setData(g); setError(null);
      if (g.rows.some((r) => r.loan_balance != null)) setShowLoan(true);
    } catch (err) { setError(readErrors(err).summary); }
  }, []);

  useEffect(() => {
    const runId = new URLSearchParams(window.location.search).get("id");
    setId(runId);
    if (runId) load(runId); else setError("Payroll tidak ditemukan.");
  }, [load]);

  const dirty = Object.keys(edits).length + Object.keys(recurring).length;
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const columns: GridColumn[] = useMemo(() => {
    const all = [...(data?.columns ?? []), ...extra.filter((c) => !(data?.columns ?? []).some((d) => d.code === c.code))];
    return [...all.filter((c) => c.kind === "earning"), ...all.filter((c) => c.kind === "deduction")];
  }, [data, extra]);
  const codes = [...columns.map((c) => c.code), ...(showLoan ? [LOAN] : [])];
  const rows = (data?.rows ?? []).filter((r) => !q.trim() || r.employee.full_name.toLowerCase().includes(q.trim().toLowerCase())
                                             || r.employee.employee_no.toLowerCase().includes(q.trim().toLowerCase()));
  const locked = !!data?.run.locked;

  const saved = (line: string, code: string): string => {
    const r = data?.rows.find((x) => x.line === line);
    if (!r) return "";
    const v = code === LOAN ? r.loan_balance : r.cells[code];
    return v == null ? "" : clean(String(Math.round(Number(v))));
  };
  const value = (line: string, code: string) => key(line, code) in edits ? edits[key(line, code)] : saved(line, code).replace(/^0$/, "");
  const setCell = (line: string, code: string, digits: string) =>
    setEdits((cur) => {
      const n = { ...cur };
      if (digits === saved(line, code).replace(/^0$/, "")) delete n[key(line, code)]; else n[key(line, code)] = digits;
      return n;
    });

  /** A paste from Excel: lines fill down from this row, tabs fill right from this column. */
  const paste = (e: ClipboardEvent<HTMLInputElement>, rowIndex: number, colIndex: number) => {
    const text = e.clipboardData.getData("text");
    if (!/[\t\n]/.test(text.trim())) return;                // one value: normal paste
    e.preventDefault();
    const lines = text.replace(/\r/g, "").replace(/\n$/, "").split("\n");
    lines.forEach((ln, i) => {
      const row = rows[rowIndex + i];
      if (!row) return;
      ln.split("\t").forEach((cell, j) => {
        const code = codes[colIndex + j];
        if (code && !row.multi.includes(code)) setCell(row.line, code, clean(cell));
      });
    });
  };

  const total = (code: string) => (data?.rows ?? []).reduce((s, r) => s + Number(value(r.line, code) || 0), 0);

  const addColumn = () => {
    const label = newLabel.trim();
    if (!label) return;
    const code = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "item";
    if (columns.some((c) => c.code === code)) { setError(`Kolom "${label}" sudah ada.`); return; }
    setExtra([...extra, { code, label, kind: newKind, standard: false, recurring: false, count: 0 }]);
    setNewLabel(""); setAdding(false); setError(null);
  };

  const save = async () => {
    if (!id || !data) return;
    setBusy(true); setError(null); setDone(null);
    try {
      const typed: [string, string][] = Object.entries(edits as Record<string, string>);
      const cells = typed.filter(([k]) => !k.endsWith(`|${LOAN}`))
        .map(([k, v]) => { const [line, code] = k.split("|"); return { line, code, amount: v || "0" }; });
      const loan_balance = typed.filter(([k]) => k.endsWith(`|${LOAN}`))
        .map(([k, v]) => ({ line: k.split("|")[0], value: v === "" ? null : v }));
      const cols = [
        ...extra.map((c) => ({ code: c.code, label: c.label, kind: c.kind, ...(c.code in recurring ? { recurring: recurring[c.code] } : {}) })),
        ...Object.entries(recurring).filter(([code]) => !extra.some((c) => c.code === code))
          .map(([code, r]) => ({ code, recurring: r })),
      ];
      const g = await payrollApi.saveItemGrid(id, { cells, columns: cols, loan_balance });
      setData(g); setEdits({}); setRecurring({});
      setExtra(extra.filter((c) => !g.columns.some((d) => d.code === c.code)));
      setDone(`Tersimpan: ${g.changed ?? 0} perubahan, ${g.recalculated ?? 0} karyawan dihitung ulang.`);
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  if (error && !data) return <div className="card" style={{ color: "var(--danger)" }}>{error}</div>;
  if (!data || !id) return <div style={{ padding: 24, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>;

  const isRecurring = (c: GridColumn) => (c.code in recurring ? recurring[c.code] : c.recurring);
  const head = (c: GridColumn) => (
    <th key={c.code} style={{ textAlign: "right", minWidth: 130, verticalAlign: "bottom", color: c.kind === "deduction" ? "var(--danger)" : undefined }}>
      <div>{c.label}</div>
      <label style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11.5, fontWeight: 500, color: "var(--steel)", textTransform: "none", letterSpacing: 0 }}
             title="Item di kolom ini disalin ke payroll bulan depan">
        <input type="checkbox" disabled={locked} checked={isRecurring(c)}
               onChange={(e) => setRecurring({ ...recurring, [c.code]: e.target.checked })} /> tiap bulan
      </label>
    </th>
  );

  return (
    <div>
      <Link href={`/dashboard/payroll/run?id=${id}`} style={{ fontSize: 13.5, display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 8 }}
            onClick={(e) => { if (dirty && !window.confirm("Ada perubahan yang belum disimpan. Tinggalkan halaman?")) e.preventDefault(); }}>
        <ArrowLeft size={14} /> {data.run.name}
      </Link>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Item manual</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14, maxWidth: 780 }}>
            Insentif, kubikasi, pinjaman dan potongan lain untuk semua karyawan sekaligus. Ketik, atau tempel satu kolom
            langsung dari Excel. Kosongkan sel untuk menghapus. Centang <b>tiap bulan</b> untuk item yang berulang
            (disalin ke payroll bulan depan).
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input className="input" placeholder="Cari nama" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 180 }} />
          {!locked && (
            <button className="btn-rust" disabled={busy || dirty === 0} onClick={save} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={15} />}
              {dirty ? `Simpan ${dirty} perubahan` : "Tidak ada perubahan"}
            </button>
          )}
        </div>
      </div>

      {locked && (
        <div style={{ background: "var(--workshop-lt)", color: "var(--workshop)", borderRadius: 8, padding: "10px 14px", fontSize: 13.5, marginBottom: 12 }}>
          <Lock size={14} style={{ verticalAlign: "-2px" }} /> Payroll ini sudah dikunci: hanya bisa dilihat.
        </div>
      )}
      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</div>}
      {done && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12, background: "var(--workshop-lt)", color: "var(--workshop)", fontWeight: 700, display: "flex", gap: 8 }}>
          {done}<button onClick={() => setDone(null)} aria-label="Tutup" style={{ marginLeft: "auto", background: "none", border: "none", color: "inherit" }}><X size={15} /></button>
        </div>
      )}

      {!locked && (
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
          {adding ? (
            <>
              <input className="input" autoFocus placeholder="Nama kolom, mis. Bongkar semen" value={newLabel} onChange={(e) => setNewLabel(e.target.value)}
                     onKeyDown={(e) => { if (e.key === "Enter") addColumn(); }} style={{ width: 240 }} />
              <select className="input" value={newKind} onChange={(e) => setNewKind(e.target.value as "earning" | "deduction")} style={{ width: 150 }}>
                <option value="earning">Penghasilan</option>
                <option value="deduction">Potongan</option>
              </select>
              <button className="btn-ghost" onClick={addColumn} disabled={!newLabel.trim()}>Tambah</button>
              <button className="btn-ghost" onClick={() => setAdding(false)}>Batal</button>
            </>
          ) : (
            <button className="btn-ghost" onClick={() => setAdding(true)} style={{ display: "flex", alignItems: "center", gap: 6 }}><Plus size={15} /> Kolom</button>
          )}
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13.5 }}>
            <input type="checkbox" checked={showLoan} onChange={(e) => setShowLoan(e.target.checked)} /> Tampilkan kolom <b>Sisa pinjaman</b> (dicetak di slip)
          </label>
        </div>
      )}

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table" style={{ minWidth: 700 }}>
          <thead>
            <tr>
              <th style={{ position: "sticky", left: 0, background: "var(--paper-2, #fff)", zIndex: 1 }}>Karyawan</th>
              {columns.map(head)}
              {showLoan && <th style={{ textAlign: "right", minWidth: 130, verticalAlign: "bottom" }}>Sisa pinjaman<div style={{ fontSize: 11.5, fontWeight: 500, color: "var(--steel)", textTransform: "none", letterSpacing: 0 }}>di slip</div></th>}
              <th style={{ textAlign: "right", verticalAlign: "bottom" }}>Bersih</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={r.line}>
                <td style={{ whiteSpace: "nowrap", position: "sticky", left: 0, background: "var(--paper-2, #fff)", zIndex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{r.employee.full_name}</div>
                  <div className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>{r.employee.employee_no}</div>
                </td>
                {codes.map((code, ci) => {
                  const multi = r.multi.includes(code);
                  const changed = key(r.line, code) in edits;
                  const v = value(r.line, code);
                  return (
                    <td key={code} style={{ textAlign: "right" }}>
                      {multi || locked ? (
                        <span title={multi ? "Lebih dari satu item: ubah di rincian karyawan (klik barisnya di payroll)" : undefined}
                              style={{ color: multi ? "var(--steel)" : undefined }}>{show(v) || "-"}{multi ? " *" : ""}</span>
                      ) : (
                        <input className="input" inputMode="numeric" value={show(v)} aria-label={`${r.employee.full_name} ${code}`}
                               onChange={(e) => setCell(r.line, code, clean(e.target.value))}
                               onPaste={(e) => paste(e, ri, ci)}
                               style={{ width: 120, textAlign: "right", padding: "4px 8px", fontSize: 13,
                                        ...(changed ? { background: "var(--hazard-light)", borderColor: "var(--hazard-dark)" } : {}) }} />
                      )}
                    </td>
                  );
                })}
                <td style={{ textAlign: "right", whiteSpace: "nowrap", fontWeight: 700 }}>{rupiah(r.net)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td style={{ fontWeight: 700, position: "sticky", left: 0, background: "var(--paper-2, #fff)" }}>Total</td>
              {codes.map((code) => <td key={code} style={{ textAlign: "right", fontWeight: 700, whiteSpace: "nowrap" }}>{total(code) ? rupiah(total(code)) : "-"}</td>)}
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 8 }}>
        Sel kuning = belum disimpan. * = karyawan punya lebih dari satu item di kolom itu: ubah di rincian karyawan.
        Kolom baru muncul tetap setelah ada isinya dan disimpan.
      </div>
    </div>
  );
}
