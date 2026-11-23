"use client";
// =============================================================================
// /dashboard/karyawan/hak-akhir?id=<employee> — "Hak akhir" (G16-4, 23 Nov 2026).
// End date + reason -> pesangon, UPMK, UPH, uang pisah or kompensasi PKWT under UU 27/2026, the PPh 21 final
// (PP 68/2009), a printable statement, and "Masukkan ke slip" for the leaver's last payslip.
// The law is the default; every amount can be changed, with a reason, and shows "berbeda dari UU".
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { FinalPayInput, FinalPayLine, FinalPayPage, FinalPayRecord, FinalPayResult, finalPayApi } from "@/lib/api/finalPay";
import { rupiah } from "@/lib/format";
import { ArrowLeft, FileCheck2, Info, Loader2, Plus, Printer, Save, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

const digits = (s: string) => s.replace(/\D/g, "").slice(0, 13);
const dateText = (iso: string) => iso.split("-").reverse().join("/");
const hint: CSSProperties = { fontSize: 12.5, color: "var(--steel)", marginTop: 3 };
const blue: CSSProperties = { fontSize: 12.5, color: "#2563A8", marginTop: 3 };

const PRINT_CSS = `
  @media print {
    body * { visibility: hidden !important; }
    .hak-print, .hak-print * { visibility: visible !important; }
    .hak-print { position: absolute; left: 0; top: 0; width: 100%; box-shadow: none !important; border: none !important; }
    .no-print { display: none !important; }
  }
`;

function fromRecord(r: FinalPayRecord, employee: string): FinalPayInput {
  return { id: r.id, employee, end_date: r.end_date, reason: r.reason, upah: r.upah, leave_days: r.leave_days,
           travel: r.travel, other_items: r.other_items, overrides: r.overrides, deduct_loan: r.deduct_loan, note: r.note };
}

function blankForm(page: FinalPayPage): FinalPayInput {
  return { id: null, employee: page.employee.id, end_date: page.defaults.end_date, reason: page.defaults.reason,
           upah: null, leave_days: null, travel: "0", other_items: [], overrides: {}, deduct_loan: false, note: "" };
}

export default function FinalPayPageView() {
  const [page, setPage] = useState<FinalPayPage | null>(null);
  const [form, setForm] = useState<FinalPayInput | null>(null);
  const [result, setResult] = useState<FinalPayResult | null>(null);
  const [editing, setEditing] = useState<string | null>(null);        // line key being changed
  const [draft, setDraft] = useState<{ amount: string; reason: string }>({ amount: "", reason: "" });
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (id: string, keep?: string) => {
    try {
      const p = await finalPayApi.load(id);
      setPage(p);
      const rec = p.records.find((r) => r.id === keep) ?? p.records[0];
      setForm(rec ? fromRecord(rec, p.employee.id) : blankForm(p));
    } catch (e) {
      setMessage({ ok: false, text: readErrors(e).summary });
    }
  }, []);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (id) load(id); else setMessage({ ok: false, text: "Pilih karyawan dari halaman Karyawan." });
  }, [load]);

  // live preview, 400 ms after the last change
  useEffect(() => {
    if (!form) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try { setResult(await finalPayApi.preview(form)); }
      catch (e) { setResult(null); setMessage({ ok: false, text: readErrors(e).summary }); }
    }, 400);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [form]);

  if (!page || !form) {
    return <div style={{ padding: 30, color: "var(--steel)" }}>
      {message ? message.text : <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />}
    </div>;
  }
  const set = <K extends keyof FinalPayInput>(k: K, v: FinalPayInput[K]) => { setMessage(null); setForm({ ...form, [k]: v }); };
  const saved = page.records.find((r) => r.id === form.id) ?? null;
  const reason = page.reasons.find((r) => r.value === form.reason);

  const startEdit = (l: FinalPayLine) => {
    setEditing(l.key);
    setDraft({ amount: l.changed ? digits(l.amount) : digits(l.law_amount), reason: l.reason });
  };
  const applyEdit = (l: FinalPayLine) => {
    const overrides = { ...form.overrides };
    if (draft.amount === "" || draft.amount === digits(l.law_amount)) delete overrides[l.key];
    else overrides[l.key] = { amount: draft.amount, reason: draft.reason.trim() };
    set("overrides", overrides);
    setEditing(null);
  };
  const backToLaw = (key: string) => {
    const overrides = { ...form.overrides };
    delete overrides[key];
    set("overrides", overrides);
  };

  const save = async () => {
    setBusy("save"); setMessage(null);
    try {
      const res = await finalPayApi.save(form);
      await load(page.employee.id, res.record.id);
      setMessage({ ok: true, text: res.message });
    } catch (e) { setMessage({ ok: false, text: readErrors(e).summary }); }
    finally { setBusy(""); }
  };
  const attach = async () => {
    if (!saved) return;
    if (!window.confirm(`Masukkan hak akhir ke slip terakhir ${page.employee.full_name}? Tanggal keluar akan diisi ${dateText(form.end_date)}.`)) return;
    setBusy("attach"); setMessage(null);
    try {
      const res = await finalPayApi.attach(saved.id);
      await load(page.employee.id, res.record.id);
      setMessage({ ok: true, text: res.message });
    } catch (e) { setMessage({ ok: false, text: readErrors(e).summary }); }
    finally { setBusy(""); }
  };
  const remove = async () => {
    if (!saved || !window.confirm("Hapus hitungan hak akhir ini?" + (saved.run ? " Hak akhir juga dihapus dari slip." : ""))) return;
    setBusy("remove"); setMessage(null);
    try {
      const text = await finalPayApi.remove(saved.id);
      await load(page.employee.id);
      setMessage({ ok: true, text });
    } catch (e) { setMessage({ ok: false, text: readErrors(e).summary }); }
    finally { setBusy(""); }
  };

  const e = page.employee;
  const locked = !!saved?.run?.locked;
  return (
    <div>
      <style>{PRINT_CSS}</style>
      <Link href="/dashboard/karyawan" className="no-print"
            style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 14, color: "var(--steel)" }}>
        <ArrowLeft size={15} /> Karyawan
      </Link>
      <h1 className="no-print" style={{ margin: "6px 0 2px" }}>Hak akhir: {e.full_name}</h1>
      <div className="no-print" style={{ color: "var(--steel)", fontSize: 14, marginBottom: 14 }}>
        {e.employee_no}{e.position ? ` · ${e.position}` : ""} · masuk {dateText(e.join_date)}. Hitungan menurut UU No. 27/2026
        (angka UU sebagai bawaan; boleh diubah dengan alasan) dan PPh 21 final PP 68/2009.
      </div>
      {message && (
        <div className="no-print" style={{ padding: "10px 14px", borderRadius: 6, marginBottom: 14, fontSize: 14,
                      background: message.ok ? "#E8F3EC" : "#FBEAEA", color: message.ok ? "#2E7D4F" : "var(--danger)" }}>
          {message.text}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 380px) minmax(0, 1fr)", gap: 18, alignItems: "start" }}>
        {/* ── the inputs ── */}
        <div className="card no-print">
          {page.records.length > 1 && (
            <div style={{ marginBottom: 12 }}>
              <label className="label">Hitungan tersimpan</label>
              <select className="input" style={{ width: "100%" }} value={form.id ?? ""}
                      onChange={(ev) => { const r = page.records.find((x) => x.id === ev.target.value);
                                          setForm(r ? fromRecord(r, e.id) : blankForm(page)); }}>
                {page.records.map((r) => <option key={r.id} value={r.id}>{dateText(r.end_date)} · {r.result.reason_label}</option>)}
                <option value="">+ Hitungan baru</option>
              </select>
            </div>
          )}
          <label className="label" htmlFor="end">Hari terakhir bekerja</label>
          <input id="end" type="date" className="input" style={{ width: "100%" }} value={form.end_date}
                 onChange={(ev) => set("end_date", ev.target.value)} />

          <label className="label" htmlFor="reason" style={{ marginTop: 12 }}>Alasan berakhirnya hubungan kerja</label>
          <select id="reason" className="input" style={{ width: "100%" }} value={form.reason}
                  onChange={(ev) => set("reason", ev.target.value)}>
            {page.reasons.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
          {reason && <div style={hint}>UU No. 27/2026 {reason.article}</div>}

          <label className="label" htmlFor="upah" style={{ marginTop: 12 }}>Upah sebulan (dasar perhitungan)</label>
          <input id="upah" className="input" inputMode="numeric" style={{ width: "100%" }}
                 placeholder={rupiah(page.defaults.upah)} value={form.upah ?? ""}
                 onChange={(ev) => set("upah", digits(ev.target.value) || null)} />
          <div style={hint}>Kosong = {rupiah(page.defaults.upah)}, {page.defaults.upah_note}.</div>

          <label className="label" htmlFor="leave" style={{ marginTop: 12 }}>Sisa cuti tahunan (hari)</label>
          <input id="leave" className="input" inputMode="decimal" style={{ width: "100%" }}
                 placeholder={page.defaults.leave_days} value={form.leave_days ?? ""}
                 onChange={(ev) => set("leave_days", ev.target.value.replace(/[^\d.]/g, "") || null)} />
          <div style={hint}>Kosong = sisa cuti di SeeGaji pada tanggal keluar. Satu hari = upah ÷ {page.defaults.daily_divisor}.</div>

          <label className="label" htmlFor="travel" style={{ marginTop: 12 }}>Ongkos pulang (Rp)</label>
          <input id="travel" className="input" inputMode="numeric" style={{ width: "100%" }} value={form.travel === "0" ? "" : form.travel}
                 placeholder="0" onChange={(ev) => set("travel", digits(ev.target.value) || "0")} />
          <div style={hint}>Untuk karyawan dan keluarga ke tempat ia diterima bekerja (Pasal 232 ayat 4 huruf b).</div>

          <div className="label" style={{ marginTop: 12 }}>Hak lain menurut PK / PP / PKB</div>
          {form.other_items.map((it, n) => (
            <div key={n} style={{ display: "flex", gap: 6, marginBottom: 6 }}>
              <input className="input" style={{ flex: 1 }} placeholder="Nama" value={it.label}
                     onChange={(ev) => set("other_items", form.other_items.map((x, k) => k === n ? { ...x, label: ev.target.value } : x))} />
              <input className="input" style={{ width: 120 }} inputMode="numeric" placeholder="Rp" value={it.amount}
                     onChange={(ev) => set("other_items", form.other_items.map((x, k) => k === n ? { ...x, amount: digits(ev.target.value) } : x))} />
              <button className="btn-ghost" aria-label="Hapus" onClick={() => set("other_items", form.other_items.filter((_, k) => k !== n))}><X size={14} /></button>
            </div>
          ))}
          <button className="btn-ghost" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                  onClick={() => set("other_items", [...form.other_items, { label: "", amount: "" }])}>
            <Plus size={14} /> Tambah hak lain
          </button>

          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 14, fontSize: 14 }}>
            <input type="checkbox" checked={form.deduct_loan} onChange={(ev) => set("deduct_loan", ev.target.checked)} />
            <span>Lunasi sisa pinjaman / kasbon dari slip terakhir
              <div style={hint}>Hanya dengan persetujuan karyawan.{result?.loan ? ` Sisa: ${rupiah(result.loan.balance)}.` : ""}</div>
            </span>
          </label>

          <label className="label" htmlFor="note" style={{ marginTop: 12 }}>Catatan (boleh kosong)</label>
          <input id="note" className="input" style={{ width: "100%" }} value={form.note} onChange={(ev) => set("note", ev.target.value)} />

          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 16 }}>
            <button className="btn-rust" onClick={save} disabled={!!busy || locked}
                    style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              {busy === "save" ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={15} />} Simpan
            </button>
            <button className="btn-ghost" onClick={attach} disabled={!saved || !!busy || locked}
                    style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              {busy === "attach" ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <FileCheck2 size={15} />} Masukkan ke slip
            </button>
            <button className="btn-ghost" onClick={() => window.print()} disabled={!result}
                    style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <Printer size={15} /> Cetak
            </button>
            {saved && (
              <button className="btn-ghost" onClick={remove} disabled={!!busy || locked}
                      style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--danger)" }}>
                <Trash2 size={15} /> Hapus
              </button>
            )}
          </div>
          <div style={hint}>
            {saved?.run ? `Sudah masuk slip di ${saved.run.name}${saved.run.locked ? " (dikunci)" : ""}.`
                        : saved ? "Tersimpan, belum masuk slip." : "Belum disimpan."}
          </div>
        </div>

        {/* ── the statement ── */}
        <div className="card hak-print">
          {!result ? (
            <div style={{ color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
          ) : (
            <>
              <div style={{ fontSize: 18, fontWeight: 800, color: "var(--midnight)" }}>Rincian hak akhir</div>
              <div style={{ fontSize: 14, marginTop: 6, lineHeight: 1.6 }}>
                <b>{e.full_name}</b> ({e.employee_no}{e.position ? `, ${e.position}` : ""})<br />
                Masuk {dateText(e.join_date)} · hari terakhir {dateText(form.end_date)} · masa kerja <b>{result.service.text}</b><br />
                Alasan: {result.reason_label} (UU No. 27/2026 {result.article})<br />
                Upah sebulan {rupiah(result.upah)} ({result.upah_note})
              </div>

              <table className="data-table" style={{ marginTop: 12 }}>
                <thead><tr><th>Komponen</th><th>Dasar</th><th style={{ textAlign: "right" }}>Jumlah</th><th className="no-print" /></tr></thead>
                <tbody>
                  {result.lines.length === 0 && (
                    <tr><td colSpan={4} style={{ color: "var(--steel)" }}>Tidak ada hak akhir untuk alasan ini.</td></tr>
                  )}
                  {result.lines.map((l) => (
                    <tr key={l.key}>
                      <td>{l.label}<div style={hint}>{l.article}</div>
                        {l.changed && (
                          <div style={blue}><Info size={12} style={{ verticalAlign: "-1px" }} /> Berbeda dari UU ({rupiah(l.law_amount)}): {l.reason}</div>
                        )}</td>
                      <td style={{ fontSize: 13 }}>{l.basis}</td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        {editing === l.key ? (
                          <div className="no-print" style={{ display: "grid", gap: 4, justifyItems: "end" }}>
                            <input className="input" inputMode="numeric" style={{ width: 130, textAlign: "right" }} value={draft.amount}
                                   onChange={(ev) => setDraft({ ...draft, amount: digits(ev.target.value) })} />
                            <input className="input" style={{ width: 200 }} placeholder="Alasan diubah" value={draft.reason}
                                   onChange={(ev) => setDraft({ ...draft, reason: ev.target.value })} />
                            <div style={{ display: "flex", gap: 4 }}>
                              <button className="btn-ghost" onClick={() => setEditing(null)}>Batal</button>
                              <button className="btn-rust" onClick={() => applyEdit(l)}
                                      disabled={draft.amount !== digits(l.law_amount) && draft.amount !== "" && !draft.reason.trim()}>Pakai</button>
                            </div>
                          </div>
                        ) : rupiah(l.amount)}
                      </td>
                      <td className="no-print" style={{ whiteSpace: "nowrap" }}>
                        {editing !== l.key && !locked && (
                          l.changed
                            ? <button className="btn-ghost" onClick={() => backToLaw(l.key)}>Kembali ke UU</button>
                            : <button className="btn-ghost" onClick={() => startEdit(l)}>Ubah</button>
                        )}
                      </td>
                    </tr>
                  ))}
                  <tr><td colSpan={2} style={{ fontWeight: 800 }}>Jumlah hak akhir</td>
                      <td style={{ textAlign: "right", fontWeight: 800, whiteSpace: "nowrap" }}>{rupiah(result.total)}</td><td className="no-print" /></tr>
                  <tr><td colSpan={2}>PPh 21 final (PP 68/2009)
                        {result.tax.steps.map((s) => <div key={s.text} style={hint}>{s.text} = {rupiah(s.tax)}</div>)}</td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>({rupiah(result.tax.amount)})</td><td className="no-print" /></tr>
                  <tr><td colSpan={2} style={{ fontWeight: 800 }}>Diterima</td>
                      <td style={{ textAlign: "right", fontWeight: 800, whiteSpace: "nowrap" }}>{rupiah(result.net)}</td><td className="no-print" /></tr>
                  {result.loan?.deducted && (
                    <>
                      <tr><td colSpan={2}>Pelunasan sisa pinjaman / kasbon (dari slip terakhir)</td>
                          <td style={{ textAlign: "right" }}>({rupiah(result.loan.balance)})</td><td className="no-print" /></tr>
                      <tr><td colSpan={2} style={{ fontWeight: 800 }}>Diterima setelah pelunasan</td>
                          <td style={{ textAlign: "right", fontWeight: 800, whiteSpace: "nowrap" }}>{rupiah(result.paid_out ?? result.net)}</td><td className="no-print" /></tr>
                    </>
                  )}
                </tbody>
              </table>

              {result.notes.map((n) => (
                <div key={n} style={blue}><Info size={12} style={{ verticalAlign: "-1px" }} /> {n}</div>
              ))}
              <div style={hint}>Gaji bulan terakhir dibayar di slip payroll seperti biasa (hari setelah tanggal keluar tidak dibayar).</div>
              {form.note && <div style={{ fontSize: 13, marginTop: 6 }}>Catatan: {form.note}</div>}

              <div style={{ display: "flex", justifyContent: "space-around", textAlign: "center", marginTop: 28, fontSize: 14 }}>
                <div>Karyawan<div style={{ height: 56 }} />{e.full_name}</div>
                <div>Perusahaan<div style={{ height: 56 }} />HRD</div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
