"use client";
// =============================================================================
// /dashboard/payroll/pinjaman — loans that pay themselves off (G13 part 2, 15 Nov 2026).
// Enter a loan once (what is still owed, the deduction per month, the first pay month): every draft payroll from
// that month deducts it, and the slip shows "Sisa pinjaman". Kasbon = the whole amount in one month.
// "Bulan ini" changes this month's deduction (0 = skip this month). Locked payrolls never change.
// =============================================================================
import { Employee, hrApi, readErrors } from "@/lib/api/hr";
import { Loan, loanApi as payrollApi } from "@/lib/api/payroll";
import { rupiah } from "@/lib/format";
import { ArrowLeft, Ban, Loader2, Plus, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const digits = (t: string) => t.replace(/[^\d]/g, "");
const show = (t: string) => (t ? new Intl.NumberFormat("id-ID").format(Number(t)) : "");
const thisMonth = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

export default function PinjamanPage() {
  const [loans, setLoans] = useState<Loan[] | null>(null);
  const [total, setTotal] = useState("0");
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [people, setPeople] = useState<Employee[]>([]);
  const [form, setForm] = useState({ employee: "", kasbon: false, amount: "", installment: "", start_month: thisMonth(), note: "" });
  const [month, setMonth] = useState<Record<string, string>>({});       // loan id -> this month's amount typed

  const load = useCallback(async () => {
    try {
      const r = await payrollApi.loans(showAll ? "all" : "active");
      setLoans(r.loans); setTotal(r.total_remaining); setError(null);
    } catch (err) { setError(readErrors(err).summary); }
  }, [showAll]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (adding && people.length === 0) hrApi.employees().then(setPeople).catch(() => undefined); }, [adding, people.length]);

  const act = async (fn: () => Promise<unknown>, text: string) => {
    setBusy(true); setError(null); setDone(null);
    try { await fn(); setDone(text); await load(); }
    catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };

  const save = () => act(async () => {
    const r = await payrollApi.createLoan({ employee: form.employee, amount: form.amount,
      installment: form.kasbon ? form.amount : form.installment, start_month: form.start_month, note: form.note.trim() });
    setAdding(false);
    setForm({ employee: "", kasbon: false, amount: "", installment: "", start_month: form.start_month, note: "" });
    return r;
  }, "Pinjaman dicatat. Payroll yang masih draft sudah dihitung ulang.");

  const ready = form.employee && Number(form.amount) > 0 && (form.kasbon || Number(form.installment) > 0) && form.start_month;
  const months = form.kasbon || !Number(form.installment) ? 1 : Math.ceil(Number(form.amount) / Number(form.installment));

  return (
    <div>
      <Link href="/dashboard/payroll" style={{ fontSize: 13.5, display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <ArrowLeft size={14} /> Payroll
      </Link>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Pinjaman & kasbon</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14, maxWidth: 760 }}>
            Catat sekali: setiap payroll mulai bulan itu memotong cicilannya sendiri, dan slip menampilkan sisa pinjaman.
            Kasbon = dipotong sekaligus bulan itu. Payroll yang sudah dikunci tidak pernah berubah.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13.5 }}>
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Tampilkan yang lunas / dibatalkan
          </label>
          <button className="btn-rust" onClick={() => setAdding(!adding)} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Plus size={15} /> Pinjaman baru
          </button>
        </div>
      </div>

      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</div>}
      {done && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12, background: "var(--workshop-lt)", color: "var(--workshop)", fontWeight: 700, display: "flex" }}>
          {done}<button onClick={() => setDone(null)} aria-label="Tutup" style={{ marginLeft: "auto", background: "none", border: "none", color: "inherit" }}><X size={15} /></button>
        </div>
      )}

      {adding && (
        <div className="card" style={{ marginBottom: 14, display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", alignItems: "end" }}>
          <div><label className="label">Karyawan</label>
            <select className="input" value={form.employee} onChange={(e) => setForm({ ...form, employee: e.target.value })}>
              <option value="">Pilih…</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.full_name} ({p.employee_no})</option>)}
            </select></div>
          <div><label className="label">Jenis</label>
            <select className="input" value={form.kasbon ? "kasbon" : "cicilan"} onChange={(e) => setForm({ ...form, kasbon: e.target.value === "kasbon" })}>
              <option value="cicilan">Cicilan (beberapa bulan)</option>
              <option value="kasbon">Kasbon (dipotong sekaligus)</option>
            </select></div>
          <div><label className="label">Sisa yang harus dibayar</label>
            <input className="input" inputMode="numeric" placeholder="mis. 2.200.000" value={show(form.amount)}
                   onChange={(e) => setForm({ ...form, amount: digits(e.target.value) })} /></div>
          {!form.kasbon && (
            <div><label className="label">Potongan per bulan</label>
              <input className="input" inputMode="numeric" placeholder="mis. 300.000" value={show(form.installment)}
                     onChange={(e) => setForm({ ...form, installment: digits(e.target.value) })} /></div>
          )}
          <div><label className="label">Mulai dipotong (bulan gaji)</label>
            <input className="input" type="month" value={form.start_month} onChange={(e) => setForm({ ...form, start_month: e.target.value })} /></div>
          <div><label className="label">Catatan (opsional)</label>
            <input className="input" placeholder="mis. pinjaman Sept, 8x" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></div>
          <div style={{ gridColumn: "1 / -1", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <button className="btn-rust" disabled={busy || !ready} onClick={save} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />} Simpan pinjaman
            </button>
            <button className="btn-ghost" onClick={() => setAdding(false)}>Batal</button>
            {ready && (
              <span style={{ fontSize: 13, color: "var(--steel)" }}>
                {form.kasbon ? `Dipotong ${rupiah(form.amount)} sekaligus.` : `Sekitar ${months} bulan (terakhir bisa lebih kecil).`}{" "}
                Bila potongan bulan itu sudah diketik di Item manual, potongan itu yang dipakai (tidak dipotong dua kali).
              </span>
            )}
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        {!loans ? (
          <div style={{ padding: 24 }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
        ) : loans.length === 0 ? (
          <div style={{ padding: 24, color: "var(--steel)" }}>Belum ada pinjaman{showAll ? "" : " yang berjalan"}.</div>
        ) : (
          <table className="data-table">
            <thead><tr>
              <th>Karyawan</th><th>Catatan</th><th style={{ textAlign: "right" }}>Pinjaman</th><th style={{ textAlign: "right" }}>Per bulan</th>
              <th>Mulai</th><th style={{ textAlign: "right" }}>Sudah dipotong</th><th style={{ textAlign: "right" }}>Bulan ini</th>
              <th style={{ textAlign: "right" }}>Sisa</th><th>Status</th><th />
            </tr></thead>
            <tbody>
              {loans.map((l) => {
                const typed = month[l.id];
                return (
                  <tr key={l.id}>
                    <td style={{ whiteSpace: "nowrap" }}><div style={{ fontWeight: 600 }}>{l.employee.full_name}</div>
                      <div className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>{l.employee.employee_no}</div></td>
                    <td style={{ fontSize: 13 }}>{l.kasbon ? "Kasbon" : "Cicilan"}{l.note ? ` · ${l.note}` : ""}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{rupiah(l.amount)}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{rupiah(l.installment)}</td>
                    <td style={{ whiteSpace: "nowrap" }}>{l.start_label}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }} title={l.history.filter((h) => h.locked).map((h) => `${h.run}: ${rupiah(h.amount)}`).join("\n")}>{rupiah(l.paid)}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      {l.this_month && l.state === "active" ? (
                        <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }} title={l.this_month.run_name}>
                          <input className="input" inputMode="numeric" value={typed !== undefined ? show(typed) : show(String(Math.round(Number(l.this_month.amount))).replace(/^0$/, ""))}
                                 placeholder="0" onChange={(e) => setMonth({ ...month, [l.id]: digits(e.target.value) })}
                                 style={{ width: 110, textAlign: "right", padding: "4px 8px", fontSize: 13 }} />
                          {typed !== undefined && (
                            <button className="btn-ghost" disabled={busy} style={{ padding: "3px 8px", fontSize: 12.5 }}
                                    onClick={() => act(() => payrollApi.updateLoan(l.id, { run: l.this_month!.run, this_month: typed || "0" }),
                                                       `${l.employee.full_name}: potongan ${l.this_month!.run_name} diubah.`)
                                                  .then(() => setMonth((m) => { const n = { ...m }; delete n[l.id]; return n; }))}>Simpan</button>
                          )}
                        </span>
                      ) : "-"}
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap", fontWeight: 700 }}>{rupiah(l.remaining)}</td>
                    <td><span className="pill" style={{ fontSize: 12, background: l.state === "active" ? "var(--midnight-soft)" : "var(--paper-3)" }}>{l.state_label}</span></td>
                    <td>
                      {l.state === "active" && (
                        <button className="btn-ghost" disabled={busy} title="Hentikan pinjaman ini" style={{ padding: "3px 8px", fontSize: 12.5, display: "flex", alignItems: "center", gap: 4 }}
                                onClick={() => window.confirm(`Hentikan pinjaman ${l.employee.full_name}? Potongan di payroll yang belum dikunci ikut dihapus; yang sudah dikunci tetap.`)
                                               && act(() => payrollApi.updateLoan(l.id, { action: "cancel" }), `Pinjaman ${l.employee.full_name} dihentikan.`)}>
                          <Ban size={13} /> Hentikan
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot><tr>
              <td colSpan={7} style={{ fontWeight: 700 }}>Total sisa</td>
              <td style={{ textAlign: "right", fontWeight: 700 }}>{rupiah(total)}</td><td colSpan={2} />
            </tr></tfoot>
          </table>
        )}
      </div>
      <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 8 }}>
        &quot;Bulan ini&quot; = potongan di payroll yang masih draft. Ketik 0 untuk menunda bulan ini; bulan berikutnya kembali normal.
        Sisa = setelah potongan bulan ini.
      </div>
    </div>
  );
}
