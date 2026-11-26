"use client";
// =============================================================================
// /dashboard/payroll/saldo-pph21 — "Saldo awal PPh 21" (G16-2, 21 Nov 2026).
// Bruto, months and PPh 21 already withheld before the company's first SeeGaji payroll, per employee per year,
// typed in or uploaded as CSV (checked first, saved only when every row is right). Used by the yearly PPh 21.
// G16-5b (26 Nov 2026, D77): each row says which masa it covers ("Masa dari / sampai"); the months follow the range,
// and the row shows an overlap with the person's SeeGaji payrolls (red) or a gap (amber).
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { OpeningCheck, OpeningImport, OpeningList, OpeningRow, payrollApi } from "@/lib/api/payroll";
import { ArrowLeft, Download, FileCheck2, Loader2, Save, Upload } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState, type CSSProperties } from "react";

// "4500000" or "4500000.00" -> "4.500.000"
function moneyText(value: string): string {
  const n = (value || "").split(".")[0].replace(/\D/g, "");
  return n ? n.replace(/\B(?=(\d{3})+(?!\d))/g, ".") : "";
}

type Draft = { months: string; bruto: string; pph: string; iuran: string; from: string; to: string };
const draftOf = (r: OpeningRow): Draft => ({ months: String(r.months), bruto: r.bruto, pph: r.pph, iuran: r.iuran,
                                            from: r.masa_from ? String(r.masa_from) : "", to: r.masa_to ? String(r.masa_to) : "" });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
// G16-5b: with a range the months are the range; "" when only one end is chosen (saving is refused, the hint says why)
const span = (d: Draft) => (d.from && d.to ? Number(d.to) - Number(d.from) + 1 : null);

function Checks({ checks }: { checks: OpeningCheck[] }) {
  if (!checks.length) return null;
  return (
    <div style={{ marginTop: 3 }}>
      {checks.map((c, i) => (
        <div key={i} title={c.text} style={{ fontSize: 12, lineHeight: 1.35, maxWidth: 260,
                                             color: c.level === "red" ? "var(--danger)" : "#8A5A00",
                                             fontWeight: c.level === "red" ? 700 : 500 }}>
          {c.level === "red" ? "✕" : "⚠"} {c.short || c.text}
        </div>
      ))}
    </div>
  );
}
const digits = (s: string) => s.replace(/\D/g, "").slice(0, 13);
const rp = (s: string) => "Rp " + moneyText(s || "0");

export default function OpeningPage() {
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  const [data, setData] = useState<OpeningList | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState<string>("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [check, setCheck] = useState<OpeningImport | null>(null);

  const load = useCallback(async (y: number) => {
    try {
      const d = await payrollApi.openings(y);
      setData(d);
      setDrafts(Object.fromEntries(d.rows.map((r) => [r.employee.id, draftOf(r)])));
    } catch (e) {
      setMessage({ ok: false, text: readErrors(e).summary });
    }
  }, []);
  useEffect(() => { load(year); }, [year, load]);

  const dirty = (r: OpeningRow) => {
    const d = drafts[r.employee.id];
    return d && (d.months !== String(r.months) || d.bruto !== r.bruto || d.pph !== r.pph || d.iuran !== r.iuran
                 || d.from !== (r.masa_from ? String(r.masa_from) : "") || d.to !== (r.masa_to ? String(r.masa_to) : ""));
  };
  const edit = (id: string, k: keyof Draft, v: string) => setDrafts({ ...drafts, [id]: { ...drafts[id], [k]: v } });

  const saveRow = async (r: OpeningRow) => {
    const d = drafts[r.employee.id];
    setBusy(r.employee.id); setMessage(null);
    try {
      const s = span(d);
      const next = await payrollApi.saveOpening({ employee_id: r.employee.id, year, months: s ?? Number(d.months || 0),
                                                  bruto: d.bruto || "0", pph: d.pph || "0", iuran: d.iuran || "0",
                                                  masa_from: d.from ? Number(d.from) : null, masa_to: d.to ? Number(d.to) : null });
      setData(next);
      const fresh = next.rows.find((x) => x.employee.id === r.employee.id);
      setDrafts({ ...drafts, ...(fresh ? { [r.employee.id]: draftOf(fresh) } : {}) });
      setMessage({ ok: true, text: `Saldo awal ${r.employee.full_name} disimpan.` });
    } catch (e) {
      setMessage({ ok: false, text: readErrors(e).summary });
    } finally {
      setBusy("");
    }
  };

  const template = () => {
    if (!data) return;
    const lines = [["no_karyawan", "nama", "masa_dari", "masa_sampai", "bulan", "bruto", "pph21", "iuran_jht_jp"].join(";"),
                   ...data.rows.map((r) => [r.employee.employee_no, r.employee.full_name, r.masa_from ?? "", r.masa_to ?? "",
                                            r.masa_from ? "" : r.months, r.bruto, r.pph, r.iuran].join(";"))];
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `saldo-awal-pph21-${year}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const upload = async (commit: boolean) => {
    if (!file) return;
    setBusy(commit ? "commit" : "check"); setMessage(null);
    try {
      const res = await payrollApi.importOpenings(year, file, commit);
      setCheck(res);
      if (res.saved) {
        setMessage({ ok: true, text: `${res.rows.length} saldo awal dari file disimpan.` });
        setFile(null); setCheck(null);
        await load(year);
      }
    } catch (e) {
      setMessage({ ok: false, text: readErrors(e).summary });
    } finally {
      setBusy("");
    }
  };

  const cell: CSSProperties = { padding: "6px 8px", borderBottom: "1px solid var(--line, #E3E8EF)", fontSize: 13.5 };
  const monthSelect = (id: string, k: "from" | "to") => (
    <select className="input" aria-label={k === "from" ? "Masa dari" : "Masa sampai"} style={{ width: 70, padding: "6px 4px" }}
            value={drafts[id]?.[k] ?? ""} onChange={(e) => edit(id, k, e.target.value)}>
      <option value="">–</option>
      {MONTHS.map((m, i) => <option key={m} value={String(i + 1)}>{m}</option>)}
    </select>
  );
  const input = (id: string, k: keyof Draft, width: number, money = true) => (
    <input className="input" inputMode="numeric" aria-label={k} style={{ width, padding: "6px 8px", textAlign: "right" }}
           value={money ? moneyText(drafts[id]?.[k] ?? "") : drafts[id]?.[k] ?? ""}
           onChange={(e) => edit(id, k, money ? digits(e.target.value) : e.target.value.replace(/\D/g, "").slice(0, 2))} />
  );

  return (
    <div style={{ maxWidth: 1100 }}>
      <Link href="/dashboard/payroll/pengaturan" style={{ fontSize: 13.5, display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <ArrowLeft size={14} /> Pengaturan payroll
      </Link>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <h1 className="display" style={{ fontSize: 28, textTransform: "none" }}>Saldo awal PPh 21</h1>
        <select className="input" value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Tahun">
          {[thisYear - 1, thisYear, thisYear + 1].map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
        Penghasilan dan PPh 21 yang sudah dipotong <b>sebelum payroll pertama di SeeGaji</b>, dari buku gaji lama atau
        bukti potong di Coretax. Dipakai untuk hitung PPh 21 setahun (Pasal 17).
      </p>
      {data && (
        <div style={{ background: "#E7F1FB", borderRadius: 8, padding: "10px 14px", fontSize: 13.5, marginBottom: 14 }}>
          Masa pajak ikut <b>{data.tax_month_label}</b>. Payroll SeeGaji di {data.year}:{" "}
          {data.runs.length ? data.runs.map((r) => `${r.name} (masa ${r.masa})`).join(" · ") : "belum ada"}.
          Isi saldo awal untuk masa pajak <b>sebelum</b> itu.
          {data.december_run ? ` Hitung setahun di ${data.december_run}.` : ""}
          {(data.masa_warnings ?? []).map((w, i) => (                                 // G16-5a
            <div key={i} style={{ marginTop: 6, color: "#8A5A00", fontWeight: 600 }}>⚠ {w.text}</div>
          ))}
          {data.totals.overlap > 0 && (                                                     // G16-5b
            <div style={{ marginTop: 6, color: "var(--danger)", fontWeight: 700 }}>
              ✕ {data.totals.overlap} saldo awal tumpang tindih dengan payroll SeeGaji: PPh 21 setahun orang itu belum
              dihitung sampai rentangnya diperbaiki.
            </div>
          )}
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ fontWeight: 800, color: "var(--midnight)", marginBottom: 6 }}>Isi dari file (CSV)</div>
        <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 10 }}>
          Unduh template (sudah berisi nama karyawan), isi di Excel, simpan sebagai CSV, lalu periksa dulu sebelum disimpan.
          Isi <b>masa_dari</b> dan <b>masa_sampai</b> (1–12 atau Jan–Des), misalnya 1 dan 9 untuk Januari–September;
          bulan boleh kosong (dihitung dari masa). Iuran = JHT 2% dan JP 1% bagian karyawan.
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button className="btn-ghost" onClick={template} disabled={!data} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Download size={15} /> Unduh template
          </button>
          <input type="file" accept=".csv,text/csv" aria-label="File CSV"
                 onChange={(e) => { setFile(e.target.files?.[0] ?? null); setCheck(null); }} />
          <button className="btn-ghost" onClick={() => upload(false)} disabled={!file || !!busy}
                  style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {busy === "check" ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <FileCheck2 size={15} />} Periksa file
          </button>
          {check && check.errors === 0 && check.rows.length > 0 && (
            <button className="btn-rust" onClick={() => upload(true)} disabled={!!busy}
                    style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {busy === "commit" ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Upload size={15} />}
              Simpan {check.rows.length} saldo awal
            </button>
          )}
        </div>
        {check && (
          <div style={{ marginTop: 12, overflowX: "auto" }}>
            <div style={{ fontSize: 13.5, marginBottom: 6, color: check.errors ? "var(--danger)" : "var(--workshop)" }}>
              {check.errors ? `${check.errors} baris perlu diperbaiki di file, lalu periksa lagi.`
                            : `Semua ${check.rows.length} baris benar. Total bruto ${rp(check.totals.bruto)}, PPh 21 ${rp(check.totals.pph)}.`}
            </div>
            <table style={{ borderCollapse: "collapse", width: "100%" }}>
              <thead><tr>{["Baris", "No.", "Nama", "Masa", "Bulan", "Bruto", "PPh 21", "Iuran", "Masalah"].map((h) =>
                <th key={h} style={{ ...cell, textAlign: "left", fontSize: 12, color: "var(--steel)" }}>{h}</th>)}</tr></thead>
              <tbody>
                {check.rows.map((r) => (
                  <tr key={r.line} style={r.errors.length ? { background: "rgba(200,60,40,0.06)" } : undefined}>
                    <td style={cell}>{r.line}</td><td style={cell}>{r.employee_no}</td><td style={cell}>{r.full_name}</td>
                    <td style={cell}>{r.masa_text || "–"}</td>
                    <td style={{ ...cell, textAlign: "right" }}>{r.months}</td>
                    <td style={{ ...cell, textAlign: "right" }}>{rp(r.bruto)}</td>
                    <td style={{ ...cell, textAlign: "right" }}>{rp(r.pph)}</td>
                    <td style={{ ...cell, textAlign: "right" }}>{rp(r.iuran)}</td>
                    <td style={{ ...cell, color: "var(--danger)" }}>{r.errors.join(", ")}<Checks checks={r.checks ?? []} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {message && <div style={{ marginBottom: 10, fontSize: 14, color: message.ok ? "var(--workshop)" : "var(--danger)" }}>{message.text}</div>}
      {!data && !message && <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />}
      {data && (
        <div className="card" style={{ overflowX: "auto", padding: 0 }}>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead><tr>{["No.", "Nama", "Masa dari", "Masa sampai", "Bulan", "Bruto", "PPh 21 dipotong", "Iuran JHT/JP", ""].map((h) =>
              <th key={h} style={{ ...cell, textAlign: h === "Nama" || h === "No." || h.startsWith("Masa") ? "left" : "right", fontSize: 12, color: "var(--steel)" }}>{h}</th>)}</tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.employee.id} style={r.employee.status === "resigned" ? { opacity: 0.7 } : undefined}>
                  <td style={cell}>{r.employee.employee_no}</td>
                  <td style={cell}>
                    {r.employee.full_name}{r.employee.status === "resigned" ? " (keluar)" : ""}
                    {r.seegaji_masa.length > 0 && (
                      <div style={{ fontSize: 11.5, color: "var(--steel)" }}>SeeGaji: masa {r.seegaji_masa.join(", ")}</div>
                    )}
                    {!dirty(r) && <Checks checks={r.checks} />}
                  </td>
                  <td style={cell}>{monthSelect(r.employee.id, "from")}</td>
                  <td style={cell}>{monthSelect(r.employee.id, "to")}</td>
                  <td style={{ ...cell, textAlign: "right" }}>
                    {span(drafts[r.employee.id] ?? draftOf(r)) !== null
                      ? <span title="Dari masa dari sampai masa sampai">{span(drafts[r.employee.id] ?? draftOf(r))}</span>
                      : input(r.employee.id, "months", 56, false)}
                  </td>
                  <td style={{ ...cell, textAlign: "right" }}>{input(r.employee.id, "bruto", 140)}</td>
                  <td style={{ ...cell, textAlign: "right" }}>{input(r.employee.id, "pph", 120)}</td>
                  <td style={{ ...cell, textAlign: "right" }}>{input(r.employee.id, "iuran", 110)}</td>
                  <td style={{ ...cell, textAlign: "right", whiteSpace: "nowrap" }}>
                    {dirty(r) ? (
                      <button className="btn-rust" onClick={() => saveRow(r)} disabled={!!busy}
                              style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "5px 10px", fontSize: 13 }}>
                        {busy === r.employee.id ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={13} />} Simpan
                      </button>
                    ) : r.saved ? <span style={{ fontSize: 12.5, color: "var(--workshop)" }}>Tersimpan</span> : null}
                  </td>
                </tr>
              ))}
              <tr>
                <td style={{ ...cell, fontWeight: 700 }} colSpan={5}>Total ({data.totals.people} karyawan tersimpan)</td>
                <td style={{ ...cell, textAlign: "right", fontWeight: 700 }}>{rp(data.totals.bruto)}</td>
                <td style={{ ...cell, textAlign: "right", fontWeight: 700 }}>{rp(data.totals.pph)}</td>
                <td style={cell} colSpan={2} />
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
