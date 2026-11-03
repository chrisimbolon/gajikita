"use client";
// =============================================================================
// /cetak/slip?run=<id>[&line=<id>] — printable pay slips (G8b part 2, 1 Nov 2026).
//
//   The layout follows the slip HR already uses (PT DKCB's): company and period at the top,
//   PENERIMAAN, PENGURANGAN, TOTAL DITERIMA KARYAWAN, then SISA PINJAMAN / SISA CUTI and
//   the two signatures. One slip per A5 page. "Cetak / Simpan PDF" uses the browser's print
//   dialog, where "Save as PDF" makes the PDF. A draft run prints a DRAFT mark on every slip.
//   No sidebar on purpose: this page is made to be printed.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { SlipBook, payrollApi } from "@/lib/api/payroll";
import { tokenStorage } from "@/lib/auth";
import { Loader2, Printer } from "lucide-react";
import { useEffect, useState } from "react";

function rp(value: string): string {
  return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(Number(value));
}

function qty(q: string | null, unit: string): string {
  if (!q || !unit) return "";
  return `${Number(q).toLocaleString("id-ID")} ${unit}`;
}

const PRINT_CSS = `
  .sheet { display: flex; justify-content: center; gap: 8mm; margin: 0 auto 10mm; break-after: page; page-break-after: always; }
  .sheet:last-child { break-after: auto; page-break-after: auto; }
  .slip { width: 130mm; background: #fff; color: #111; border: 1px solid #013D5A; box-sizing: border-box;
          font-size: 9.5pt; line-height: 1.35; position: relative; }
  .slip .top td { vertical-align: top; }
  .slip .top td:nth-child(1), .slip .top td:nth-child(2) { white-space: nowrap; }
  .slip .head { text-align: center; font-weight: 800; font-size: 11pt; padding: 6px 0; border-bottom: 1px solid #013D5A; letter-spacing: .04em; }
  .slip .top { display: flex; justify-content: space-between; gap: 10px; padding: 8px 10px; border-bottom: 1px solid #013D5A; }
  .slip .body { padding: 8px 10px; }
  .slip .row { display: flex; gap: 6px; }
  .slip .row .l { flex: 1; } .slip .row .q { width: 70px; font-style: italic; color: #444; } .slip .row .a { width: 90px; text-align: right; }
  .slip .sum { display: flex; justify-content: space-between; font-weight: 700; border-top: 1px solid #111; margin-top: 2px; padding-top: 2px; }
  .slip .title { font-weight: 800; margin: 6px 0 2px; }
  .slip .net { display: flex; justify-content: space-between; align-items: center; font-weight: 800; margin-top: 10px; }
  .slip .net .box { background: #E3EAF0; border: 1px solid #013D5A; padding: 3px 10px; min-width: 110px; text-align: right; }
  .slip .red { color: #B42318; font-weight: 700; }
  .slip .sign { display: flex; justify-content: space-around; text-align: center; border-top: 1px solid #013D5A; padding: 8px 10px 10px; }
  .slip .sign .gap { height: 38px; }
  .slip .draft { position: absolute; top: 40%; left: 0; right: 0; text-align: center; font-size: 46pt; font-weight: 800;
                 color: rgba(180, 35, 24, .12); transform: rotate(-18deg); pointer-events: none; }
  @media print {
    body { background: #fff !important; }
    .no-print { display: none !important; }
    .sheet { margin: 0 auto; }
    .slip { border-color: #013D5A; }
  }
`;

// G9b: A5 = one slip per page (as before); A4 = two slips side by side on A4 landscape, cut in the middle.
const PAGE_CSS = {
  a5: "@page { size: A5 portrait; margin: 9mm; }",
  a4: "@page { size: A4 landscape; margin: 8mm; } .sheet { gap: 10mm; } .slip { width: 133mm; }",
};
type Layout = keyof typeof PAGE_CSS;
const LAYOUT_KEY = "gajikita.slip.layout";

export default function SlipPrintPage() {
  const [book, setBook] = useState<SlipBook | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [layout, setLayoutState] = useState<Layout>("a5");
  useEffect(() => {
    try { if (localStorage.getItem(LAYOUT_KEY) === "a4") setLayoutState("a4"); } catch { /* no storage: keep A5 */ }
  }, []);
  const setLayout = (l: Layout) => {
    setLayoutState(l);
    try { localStorage.setItem(LAYOUT_KEY, l); } catch { /* fine */ }
  };

  useEffect(() => {
    if (!tokenStorage.getAccess()) { window.location.href = "/login"; return; }
    const q = new URLSearchParams(window.location.search);
    const run = q.get("run");
    if (!run) { setError("Payroll tidak ditemukan."); return; }
    payrollApi.slips(run, q.get("line") ?? undefined).then(setBook).catch((err) => setError(readErrors(err).summary));
  }, []);

  if (error) return <div style={{ padding: 24, color: "var(--danger)" }}>{error}</div>;
  if (!book) return <div style={{ padding: 24 }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>;

  const per = layout === "a4" ? 2 : 1;
  const sheets: SlipBook["slips"][] = [];
  for (let i = 0; i < book.slips.length; i += per) sheets.push(book.slips.slice(i, i + per));

  return (
    <div style={{ background: "var(--paper)", minHeight: "100vh", padding: "16px 0" }}>
      <style>{PRINT_CSS + PAGE_CSS[layout]}</style>
      <div className="no-print" style={{ maxWidth: 640, margin: "0 auto 14px", display: "flex", alignItems: "center", gap: 10, padding: "0 12px" }}>
        <div style={{ flexGrow: 1 }}>
          <div style={{ fontWeight: 800, color: "var(--midnight)" }}>Slip gaji · {book.run.name}</div>
          <div style={{ fontSize: 13, color: "var(--steel)" }}>
            {book.slips.length} slip{book.run.draft ? " · DRAFT (payroll belum dikunci)" : ""}. Pilih "Save as PDF" di dialog cetak untuk membuat PDF.
          </div>
        </div>
        <div style={{ display: "inline-flex", border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}>
          {([["a5", "A5 · 1 slip"], ["a4", "A4 · 2 slip"]] as const).map(([k, label]) => (
            <button key={k} onClick={() => setLayout(k)} style={{ padding: "6px 10px", fontSize: 13, fontWeight: 700, border: "none",
                    whiteSpace: "nowrap", background: layout === k ? "var(--midnight-soft)" : "#fff",
                    color: layout === k ? "var(--midnight)" : "var(--steel)" }}>{label}</button>
          ))}
        </div>
        <button className="btn-rust" onClick={() => window.print()} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Printer size={15} /> Cetak / Simpan PDF
        </button>
      </div>

      {sheets.map((group, gi) => (
        <div key={gi} className="sheet">
      {group.map((s) => (
        <div key={s.line_id} className="slip">
          {book.run.draft && <div className="draft">DRAFT</div>}
          <div className="head">SLIP GAJI</div>
          <div className="top">
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700 }}>{book.company.name}</div>
              <div style={{ whiteSpace: "pre-line" }}>{book.company.address}</div>
            </div>
            <table style={{ fontSize: "9pt", borderCollapse: "collapse" }}>
              <tbody>
                <tr><td>Periode</td><td style={{ padding: "0 4px" }}>:</td><td>{book.run.period}</td></tr>
                <tr><td>Karyawan</td><td style={{ padding: "0 4px" }}>:</td><td>{s.employee.full_name}</td></tr>
                <tr><td>Jabatan</td><td style={{ padding: "0 4px" }}>:</td><td>{s.employee.position || "-"}</td></tr>
                <tr><td>No. karyawan</td><td style={{ padding: "0 4px" }}>:</td><td>{s.employee.employee_no}</td></tr>
              </tbody>
            </table>
          </div>
          <div className="body">
            <div className="title">PENERIMAAN</div>
            {s.earnings.map((l, n) => (
              <div key={`e${n}`} className="row"><span className="l">- {l.label}</span><span className="q">{qty(l.quantity, l.unit)}</span><span className="a">{rp(l.amount)}</span></div>
            ))}
            <div className="sum"><span>Total Penghasilan Bruto</span><span>{rp(s.gross)}</span></div>

            <div className="title">PENGURANGAN</div>
            {s.deductions.length === 0 && <div className="row"><span className="l">-</span></div>}
            {s.deductions.map((l, n) => (
              <div key={`d${n}`} className="row"><span className="l">- {l.label}</span><span className="q">{qty(l.quantity, l.unit)}</span><span className="a">({rp(l.amount)})</span></div>
            ))}
            <div className="sum"><span>Total Pengurangan</span><span>({rp(s.deductions_total)})</span></div>

            <div className="net"><span>TOTAL DITERIMA KARYAWAN</span><span className="box">{rp(s.net)}</span></div>

            <div style={{ marginTop: 12 }}>
              <div className="row"><span className="l red">SISA PINJAMAN</span><span className="a red">{s.loan_balance ? rp(s.loan_balance) : "-"}</span></div>
              <div className="row"><span className="l red">SISA CUTI</span><span className="a red">{s.leave_left === null ? "-" : `${s.leave_left} HARI`}</span></div>
            </div>
          </div>
          <div style={{ textAlign: "center", padding: "4px 0 2px" }}>
            {book.place ? `${book.place}, ` : ""}{book.run.pay_date}
          </div>
          <div className="sign">
            <div><div>Penerima</div><div className="gap" /><div>{s.employee.full_name}</div></div>
            <div><div>{book.company.name}</div><div className="gap" /><div>{book.signer}</div></div>
          </div>
        </div>
      ))}
        </div>
      ))}
    </div>
  );
}
