"use client";
// =============================================================================
// /dashboard/payroll/run?id=... — one pay run (G8b part 1, 1 Nov 2026).
//
//   The register (one row per employee, a column per pay component), totals and
//   warnings. Click a row: the numbers taken from attendance and leave (HR can
//   correct them), extra items (per-m3 pay, incentives, kasbon, PPh 21...), the
//   slip preview. Then "Kunci": the run and its attendance days are locked.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { LineDetail, RunDetail, dayLabel, payrollApi, periodLabel } from "@/lib/api/payroll";
import { rupiah } from "@/lib/format";
import { AlertTriangle, ArrowLeft, Download, Landmark, Loader2, Lock, Printer, RefreshCw, Trash2, Unlock, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const EARNING_SUGGESTIONS = ["Kubikasi TM", "Kubikasi CP", "Bongkar Semen", "Insentif BPJS Kesehatan", "Insentif lainnya", "Bonus"];
const DEDUCTION_SUGGESTIONS = ["Kasbon", "Pinjaman", "PPh 21", "Koperasi", "Potongan lainnya"];

function money(v: string | undefined) {
  return v && Number(v) !== 0 ? rupiah(v) : "-";
}

function toCsv(d: RunDetail): string {
  const head = ["No. karyawan", "Nama", ...d.columns.filter((c) => c.side === "earnings").map((c) => c.label), "Bruto",
                ...d.columns.filter((c) => c.side === "deductions").map((c) => c.label), "Total potongan", "Bersih"];
  const rows = d.rows.map((r) => [r.employee.employee_no, r.employee.full_name,
    ...d.columns.filter((c) => c.side === "earnings").map((c) => r.amounts[c.code] ?? "0"), r.gross,
    ...d.columns.filter((c) => c.side === "deductions").map((c) => r.amounts[c.code] ?? "0"), r.deductions, r.net]);
  return [head, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\r\n");
}

// ── one employee ──
function LinePanel({ runId, lineId, locked, onClose, onChanged }: {
  runId: string; lineId: string; locked: boolean; onClose: () => void; onChanged: () => void;
}) {
  const [line, setLine] = useState<LineDetail | null>(null);
  const [fix, setFix] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [loan, setLoan] = useState("");
  const [item, setItem] = useState({ kind: "earning" as "earning" | "deduction", label: "", amount: "", recurring: false, note: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const show = (l: LineDetail) => {
    setLine(l); setFix(l.override); setNote(l.note);
    setLoan(l.loan_balance ? String(Math.round(Number(l.loan_balance))) : "");
  };

  useEffect(() => {
    payrollApi.line(runId, lineId).then(show).catch((err) => setError(readErrors(err).summary));
  }, [runId, lineId]);

  const act = async (fn: () => Promise<LineDetail>) => {
    setBusy(true);
    setError(null);
    try { show(await fn()); onChanged(); return true; }
    catch (err) { setError(readErrors(err).summary); return false; }
    finally { setBusy(false); }
  };

  if (!line) {
    return (
      <div style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: 520, maxWidth: "100%", background: "#FFFFFF", zIndex: 40, padding: 24,
                    boxShadow: "-8px 0 24px rgba(1,61,90,0.15)" }}>
        {error ?? <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />}
      </div>
    );
  }

  const a = line.auto;
  const autoValue: Record<string, number> = {
    overtime_hours: a.overtime.reduce((s, o) => s + o.minutes, 0) / 60, rest_days_worked: a.overtime.filter((o) => o.rest_day).length,
    meal_days: a.meal_days, late_minutes: a.late_minutes, unpaid_days: a.unpaid_days,
  };
  const facts: [string, string][] = [
    ["Hadir", `${a.present_days} hari`], ["Tidak hadir", `${a.absent_days} hari`],
    ["Cuti / izin dibayar", `${a.paid_leave_days} hari`], ["Izin tanpa upah", `${a.unpaid_leave_days} hari`],
    ["Di luar masa kerja", `${a.outside_days} hari`], ["Lembur disetujui", `${a.overtime.length} hari`],
  ];
  const suggestions = item.kind === "earning" ? EARNING_SUGGESTIONS : DEDUCTION_SUGGESTIONS;

  return (
    <div style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: 540, maxWidth: "100%", background: "#FFFFFF", zIndex: 40,
                  overflowY: "auto", boxShadow: "-8px 0 24px rgba(1,61,90,0.15)" }}>
      <div style={{ background: "var(--midnight)", color: "#FFFFFF", padding: "18px 20px", position: "sticky", top: 0, zIndex: 1 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 19, fontWeight: 800 }}>{line.employee.full_name}</div>
            <div style={{ fontSize: 13, color: "var(--on-dark-muted)" }}>
              {line.employee.employee_no} · {line.employee.pay_type_label} · {rupiah(line.employee.base_rate)}
              {line.employee.pay_type === "daily" ? " / hari" : ""}
            </div>
          </div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none", color: "#FFFFFF" }}><X size={20} /></button>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 12, fontSize: 14 }}>
          <span>Bruto {rupiah(line.gross)}</span><span>Potongan {rupiah(line.deductions)}</span>
          <span style={{ fontWeight: 800, color: "var(--marigold)" }}>Bersih {rupiah(line.net)}</span>
        </div>
      </div>

      <div style={{ padding: 20 }}>
        {error && <div style={{ color: "var(--danger)", fontSize: 13.5, marginBottom: 10 }}>{error}</div>}

        {line.result.warnings.length > 0 && (
          <div style={{ background: "var(--hazard-light)", borderRadius: 8, padding: "10px 12px", marginBottom: 16 }}>
            {line.result.warnings.map((w) => (
              <div key={w} style={{ fontSize: 13, color: "var(--hazard-dark)", marginBottom: 2 }}>
                <AlertTriangle size={12} style={{ verticalAlign: "-1px" }} /> {w}
              </div>
            ))}
            {a.review_days > 0 && (
              <Link href="/dashboard/absensi/tinjau" style={{ fontSize: 13, fontWeight: 600 }}>Buka Perlu Tinjau →</Link>
            )}
          </div>
        )}

        <div className="label" style={{ marginBottom: 6 }}>Dari absensi & cuti</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px", fontSize: 13.5, marginBottom: 6 }}>
          {facts.map(([k, v]) => <div key={k} style={{ display: "flex", justifyContent: "space-between" }}><span style={{ color: "var(--steel)" }}>{k}</span><span>{v}</span></div>)}
        </div>
        {Object.keys(a.leave).length > 0 && (
          <div style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 6 }}>
            {Object.entries(a.leave).map(([k, v]) => `${k} ${v} hari`).join(" · ")}
          </div>
        )}

        <div className="label" style={{ margin: "14px 0 6px" }}>Angka untuk gaji {locked ? "" : "(kosongkan = pakai angka absensi)"}</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {Object.entries(line.override_fields).map(([key, label]) => (
            <label key={key}>
              <div style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 3 }}>
                {label} <span style={{ color: "var(--ink)" }}>· absensi: {autoValue[key] ?? 0}</span>
              </div>
              <input className="input" inputMode="decimal" disabled={locked} value={fix[key] ?? ""} placeholder={String(autoValue[key] ?? 0)}
                     onChange={(e) => setFix({ ...fix, [key]: e.target.value.replace(",", ".") })} style={{ width: "100%",
                     borderColor: fix[key] ? "var(--marigold)" : undefined }} />
            </label>
          ))}
        </div>
        {!locked && (
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Alasan koreksi (mis. laporan mandor)" style={{ flexGrow: 1 }} />
            <button className="btn-ghost" disabled={busy}
                    onClick={() => act(() => payrollApi.saveLine(runId, lineId, { override: fix, note }))}>Simpan angka</button>
          </div>
        )}

        <div className="label" style={{ margin: "18px 0 6px" }}>Tambahan & potongan lain</div>
        {line.items.length === 0 && <div style={{ fontSize: 13.5, color: "var(--steel)" }}>Belum ada.</div>}
        {line.items.map((i) => (
          <div key={i.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderTop: "1px solid var(--line)", fontSize: 13.5 }}>
            <span className="pill" style={{ background: i.kind === "earning" ? "var(--workshop-lt)" : "var(--danger-light)",
                                            color: i.kind === "earning" ? "var(--workshop)" : "var(--danger)" }}>
              {i.kind === "earning" ? "+" : "−"}
            </span>
            <span style={{ flexGrow: 1 }}>{i.label}{i.recurring && <span style={{ color: "var(--steel)", fontSize: 12 }}> · tiap bulan</span>}
              {i.note && <span style={{ color: "var(--steel)", fontSize: 12 }}> · {i.note}</span>}</span>
            <span style={{ fontWeight: 700 }}>{rupiah(i.amount)}</span>
            {!locked && (
              <button aria-label="Hapus" disabled={busy} onClick={() => act(() => payrollApi.deleteItem(runId, i.id))}
                      style={{ background: "none", border: "none", color: "var(--steel)" }}><Trash2 size={14} /></button>
            )}
          </div>
        ))}
        {!locked && (
          <div style={{ background: "var(--paper)", borderRadius: 8, padding: 12, marginTop: 8 }}>
            <div style={{ display: "grid", gridTemplateColumns: "120px 1fr 130px", gap: 8 }}>
              <select className="input" value={item.kind} onChange={(e) => setItem({ ...item, kind: e.target.value as "earning" | "deduction" })}>
                <option value="earning">+ Tambahan</option>
                <option value="deduction">− Potongan</option>
              </select>
              <input className="input" list="item-labels" value={item.label} onChange={(e) => setItem({ ...item, label: e.target.value })} placeholder="Nama item" />
              <input className="input" inputMode="numeric" value={item.amount} placeholder="Rp"
                     onChange={(e) => setItem({ ...item, amount: e.target.value.replace(/[^\d]/g, "") })} />
            </div>
            <datalist id="item-labels">{suggestions.map((s) => <option key={s} value={s} />)}</datalist>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
              <input className="input" value={item.note} onChange={(e) => setItem({ ...item, note: e.target.value })} placeholder="Catatan (boleh kosong)" style={{ flexGrow: 1 }} />
              <label style={{ fontSize: 13, display: "flex", gap: 6, alignItems: "center", whiteSpace: "nowrap" }}>
                <input type="checkbox" checked={item.recurring} onChange={(e) => setItem({ ...item, recurring: e.target.checked })} /> Tiap bulan
              </label>
              <button className="btn-rust" disabled={busy || !item.label.trim() || !item.amount} style={{ whiteSpace: "nowrap" }}
                      onClick={async () => {
                        const ok = await act(() => payrollApi.addItem(runId, lineId, { ...item, amount: item.amount }));
                        if (ok) setItem({ ...item, label: "", amount: "", note: "" });
                      }}>Tambah</button>
            </div>
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "18px 0 6px" }}>
          <div className="label" style={{ margin: 0 }}>Slip</div>
          <a href={`/cetak/slip?run=${runId}&line=${lineId}`} target="_blank" rel="noreferrer"
             style={{ fontSize: 13, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 4 }}>
            <Printer size={13} /> Cetak slip ini
          </a>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
          <span style={{ fontSize: 13, color: "var(--steel)", whiteSpace: "nowrap" }}>Sisa pinjaman di slip (Rp)</span>
          <input className="input" inputMode="numeric" disabled={locked} value={loan} placeholder="-"
                 onChange={(e) => setLoan(e.target.value.replace(/[^\d]/g, ""))} style={{ flexGrow: 1 }} />
          {!locked && (
            <button className="btn-ghost" disabled={busy} style={{ whiteSpace: "nowrap" }}
                    onClick={() => act(() => payrollApi.saveLine(runId, lineId, { loan_balance: loan || null }))}>Simpan</button>
          )}
        </div>
        <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: 12, fontSize: 13.5 }}>
          {[["Penerimaan", line.result.earnings], ["Potongan", line.result.deductions]].map(([title, rows]) => (
            <div key={title as string} style={{ marginBottom: 8 }}>
              <div style={{ fontWeight: 700, marginBottom: 2 }}>{title as string}</div>
              {(rows as LineDetail["result"]["earnings"]).map((l, n) => (
                <div key={`${l.code}-${n}`} style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}>
                  <span>{l.label}{l.quantity && l.unit ? <span style={{ color: "var(--steel)" }}> · {Number(l.quantity).toLocaleString("id-ID")} {l.unit}</span> : null}</span>
                  <span>{title === "Potongan" ? `(${rupiah(l.amount)})` : rupiah(l.amount)}</span>
                </div>
              ))}
            </div>
          ))}
          <div style={{ display: "flex", justifyContent: "space-between", borderTop: "2px solid var(--midnight)", paddingTop: 6, fontWeight: 800 }}>
            <span>Total diterima</span><span>{rupiah(line.net)}</span>
          </div>
          {line.result.employer.length > 0 && (
            <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 8 }}>
              Ditanggung perusahaan: {line.result.employer.map((l) => `${l.label} ${rupiah(l.amount)}`).join(" · ")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function PayRunPage() {
  const [id, setId] = useState<string | null>(null);
  const [data, setData] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async (runId: string) => {
    try { setData(await payrollApi.run(runId)); setError(null); }
    catch (err) { setError(readErrors(err).summary); }
  }, []);

  useEffect(() => {
    const runId = new URLSearchParams(window.location.search).get("id");
    setId(runId);
    if (runId) load(runId); else setError("Payroll tidak ditemukan.");
  }, [load]);

  if (error && !data) return <div className="card" style={{ color: "var(--danger)" }}>{error}</div>;
  if (!data || !id) return <div style={{ padding: 24, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>;

  const run = data.run;
  const locked = run.status === "locked";
  const earnings = data.columns.filter((c) => c.side === "earnings");
  const deductions = data.columns.filter((c) => c.side === "deductions");

  const recalc = async () => {
    setBusy(true);
    try { setData(await payrollApi.recalculate(id)); setError(null); }
    catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };
  const lockOrOpen = async () => {
    let note = "";
    if (locked) {
      note = window.prompt("Alasan membuka kunci payroll ini:") ?? "";
      if (!note.trim()) return;
    } else if (!window.confirm(`Kunci ${run.name}? Absensi ${periodLabel(run.period_start, run.period_end)} ikut dikunci dan tidak bisa diubah.`)) {
      return;
    }
    setBusy(true);
    try { await payrollApi.lock(id, locked ? "reopen" : "lock", note); await load(id); }
    catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!window.confirm(`Hapus ${run.name} (draft)? Item tambahan di dalamnya ikut terhapus.`)) return;
    try { await payrollApi.deleteRun(id); window.location.href = "/dashboard/payroll"; }
    catch (err) { setError(readErrors(err).summary); }
  };
  const download = () => {
    const blob = new Blob(["﻿" + toCsv(data)], { type: "text/csv;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${run.name.replace(/\s+/g, "-").toLowerCase()}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const bankFile = async () => {
    try {
      const t = await payrollApi.transfers(id);
      if (t.problems > 0) {
        const names = t.rows.filter((r) => r.problem).map((r) => `- ${r.full_name}: ${r.problem}`).join("\n");
        if (!window.confirm(`${t.problems} karyawan tidak masuk file transfer:\n${names}\n\nLanjut buat file untuk ${t.ready} karyawan?`)) return;
      }
      const note = `Gaji ${run.name.replace(/^Payroll /, "")}`;
      const head = ["No", "No. karyawan", "Nama", "Bank", "No. rekening", "Nama pemilik rekening", "Jumlah", "Keterangan"];
      const rows = t.rows.filter((r) => !r.problem).map((r, n) => [String(n + 1), r.employee_no, r.full_name, r.bank_name,
        `="${r.account_no}"`, r.account_name, String(Math.round(Number(r.amount))), note]);
      const csv = [head, ...rows].map((r) => r.map((c) => `"${c.replace(/"/g, '""')}"`).join(";")).join("\r\n");
      const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `transfer-${run.name.replace(/\s+/g, "-").toLowerCase()}.csv`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (err) {
      setError(readErrors(err).summary);
    }
  };

  const cards: [string, string][] = [
    ["Karyawan", String(run.people)], ["Total bruto", rupiah(run.gross)], ["Total potongan", rupiah(run.deductions)],
    ["Total ditransfer", rupiah(run.net)], ["BPJS ditanggung perusahaan", rupiah(run.employer_cost)],
  ];

  return (
    <div>
      <Link href="/dashboard/payroll" style={{ fontSize: 13.5, display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <ArrowLeft size={14} /> Payroll
      </Link>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>
            {run.name}{" "}
            {locked
              ? <span className="pill" style={{ background: "var(--workshop-lt)", color: "var(--workshop)", fontSize: 13, verticalAlign: "middle" }}><Lock size={12} /> Dikunci</span>
              : <span className="pill" style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", fontSize: 13, verticalAlign: "middle" }}>Draft</span>}
          </h1>
          <div style={{ color: "var(--steel)", fontSize: 14 }}>
            Periode {periodLabel(run.period_start, run.period_end)} · gajian {run.pay_date ? dayLabel(run.pay_date) : "-"}
            {locked && run.locked_by ? ` · dikunci oleh ${run.locked_by}` : ""}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {!locked && (
            <button className="btn-ghost" onClick={recalc} disabled={busy} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <RefreshCw size={15} style={busy ? { animation: "spin 1s linear infinite" } : undefined} /> Hitung ulang
            </button>
          )}
          <button className="btn-ghost" onClick={download} style={{ display: "flex", alignItems: "center", gap: 6 }}><Download size={15} /> CSV</button>
          <a href={`/cetak/slip?run=${id}`} target="_blank" rel="noreferrer" className="btn-ghost"
             style={{ display: "flex", alignItems: "center", gap: 6, textDecoration: "none" }}><Printer size={15} /> Slip gaji</a>
          {locked && (
            <button className="btn-ghost" onClick={bankFile} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Landmark size={15} /> File transfer bank
            </button>
          )}
          {!locked && (
            <button className="btn-ghost" onClick={remove} disabled={busy} style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--danger)" }}>
              <Trash2 size={15} /> Hapus
            </button>
          )}
          <button className="btn-rust" onClick={lockOrOpen} disabled={busy} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {locked ? <><Unlock size={15} /> Buka kunci</> : <><Lock size={15} /> Kunci payroll</>}
          </button>
        </div>
      </div>

      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, marginBottom: 14 }}>
        {cards.map(([label, value]) => (
          <div key={label} className="card" style={{ padding: "12px 16px" }}>
            <div style={{ fontSize: 20, fontWeight: 800 }}>{value}</div>
            <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{label}</div>
          </div>
        ))}
      </div>
      {run.warnings > 0 && (
        <div style={{ background: "var(--hazard-light)", color: "var(--hazard-dark)", borderRadius: 8, padding: "10px 14px", fontSize: 13.5, marginBottom: 12 }}>
          <AlertTriangle size={14} style={{ verticalAlign: "-2px" }} /> {run.warnings} peringatan di {data.rows.filter((r) => r.warning_count > 0).length} karyawan.
          Klik barisnya untuk melihat. Peringatan tidak menghalangi payroll.
        </div>
      )}

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table" style={{ minWidth: 900 }}>
          <thead>
            <tr>
              <th>Karyawan</th>
              {earnings.map((c) => <th key={c.code} style={{ textAlign: "right" }}>{c.label}</th>)}
              <th style={{ textAlign: "right" }}>Bruto</th>
              {deductions.map((c) => <th key={c.code} style={{ textAlign: "right", color: "var(--danger)" }}>{c.label}</th>)}
              <th style={{ textAlign: "right" }}>Bersih</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.id} onClick={() => setOpen(r.id)} style={{ cursor: "pointer", background: open === r.id ? "var(--midnight-soft)" : undefined }}>
                <td style={{ whiteSpace: "nowrap" }}>
                  <div style={{ fontWeight: 600 }}>{r.employee.full_name}</div>
                  <div className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>
                    {r.employee.employee_no}{r.corrected ? " · dikoreksi" : ""}
                  </div>
                </td>
                {earnings.map((c) => <td key={c.code} style={{ textAlign: "right", whiteSpace: "nowrap" }}>{money(r.amounts[c.code])}</td>)}
                <td style={{ textAlign: "right", whiteSpace: "nowrap", fontWeight: 600 }}>{rupiah(r.gross)}</td>
                {deductions.map((c) => <td key={c.code} style={{ textAlign: "right", whiteSpace: "nowrap" }}>{money(r.amounts[c.code])}</td>)}
                <td style={{ textAlign: "right", whiteSpace: "nowrap", fontWeight: 800 }}>{rupiah(r.net)}</td>
                <td>{r.warning_count > 0 && <AlertTriangle size={14} style={{ color: "var(--hazard-dark)" }} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && (
        <LinePanel key={open} runId={id} lineId={open} locked={locked} onClose={() => setOpen(null)} onChanged={() => load(id)} />
      )}
    </div>
  );
}
