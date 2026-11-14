"use client";
// =============================================================================
// /dashboard/absensi/tinjau/catatan — HR's notes -> decisions (G17-4, 14 Nov 2026).
// The notes imported from the recap ("UL", "Izin pulang cepat", "Cuti sakit mata", "Mati lampu") grouped by
// what they mean; HR checks a group and applies it once, instead of deciding day by day.
// =============================================================================
import { NoteDecisions, NoteGroup, NoteRow, noteDecisionApi } from "@/lib/api/noteDecisions";
import { readErrors } from "@/lib/api/hr";
import { CheckCircle2, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const day = (iso: string) => { const [, m, d] = iso.split("-").map(Number); return `${d} ${MONTHS[m - 1]}`; };
const key = (r: NoteRow) => `${r.employee.id}|${r.date}`;

const STATE: Record<string, { text: string; color: string }> = {
  done:    { text: "Sudah",            color: "var(--workshop)" },
  locked:  { text: "Terkunci",         color: "var(--steel)" },
  no_taps: { text: "Tidak ada tap",    color: "var(--hazard-dark)" },
  info:    { text: "",                 color: "var(--steel)" },
  todo:    { text: "Belum",            color: "var(--ink)" },
};

function GroupCard({ g, busy, onApply }: { g: NoteGroup; busy: boolean;
                                          onApply: (g: NoteGroup, items: { row: NoteRow; choice: string }[]) => void }) {
  const todo = g.rows.filter((r) => r.state === "todo");
  const [picked, setPicked] = useState<Set<string>>(new Set(todo.map(key)));
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [open, setOpen] = useState(g.actionable && todo.length > 0);
  useEffect(() => { setPicked(new Set(g.rows.filter((r) => r.state === "todo").map(key))); }, [g]);

  const chosen = todo.filter((r) => picked.has(key(r)));
  const missing = g.choices.length > 0 && chosen.some((r) => !choice[key(r)]);
  const toggle = (k: string) => setPicked((cur) => { const n = new Set(cur); if (n.has(k)) n.delete(k); else n.add(k); return n; });

  return (
    <div className="card" style={{ padding: 0, marginBottom: 14 }}>
      <button type="button" onClick={() => setOpen(!open)} style={{ width: "100%", textAlign: "left", background: "none", border: 0,
              padding: "14px 18px", cursor: "pointer", display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontWeight: 700, fontSize: 15.5 }}>{g.label}</span>
        <span className="pill" style={{ fontSize: 12, background: "var(--paper-3)" }}>{g.rows.length} catatan</span>
        {g.actionable && (g.todo > 0
          ? <span className="pill" style={{ fontSize: 12, background: "var(--hazard-light)", fontWeight: 700 }}>{g.todo} belum</span>
          : g.rows.length > 0 && <span style={{ fontSize: 12.5, color: "var(--workshop)", fontWeight: 700 }}><CheckCircle2 size={13} style={{ verticalAlign: "-2px" }} /> selesai</span>)}
        <span style={{ marginLeft: "auto", fontSize: 12.5, color: "var(--steel)" }}>{open ? "Tutup" : "Lihat"}</span>
      </button>
      {open && (
        <div style={{ padding: "0 18px 16px" }}>
          <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 10 }}>{g.explain}</div>
          {g.rows.length === 0 ? (
            <div style={{ fontSize: 13.5, color: "var(--steel)" }}>Tidak ada catatan di periode ini.</div>
          ) : (
            <table className="data-table">
              <thead><tr>
                {g.actionable && <th style={{ width: 34 }} />}
                <th>Tanggal</th><th>Karyawan</th><th>Catatan</th><th>Tap</th>
                {g.choices.length > 0 && <th>Pilihan</th>}
                {g.actionable && <th>Status</th>}
              </tr></thead>
              <tbody>
                {g.rows.map((r) => {
                  const k = key(r);
                  const can = r.state === "todo";
                  return (
                    <tr key={k} style={{ opacity: can || !g.actionable ? 1 : 0.6 }}>
                      {g.actionable && <td>{can && <input type="checkbox" checked={picked.has(k)} onChange={() => toggle(k)} />}</td>}
                      <td style={{ whiteSpace: "nowrap", fontSize: 13.5 }}>{day(r.date)}</td>
                      <td style={{ fontSize: 13.5 }}><b>{r.employee.full_name}</b> <span style={{ color: "var(--steel)", fontSize: 12 }}>{r.employee.employee_no}</span></td>
                      <td style={{ fontSize: 13.5 }}>{r.text}</td>
                      <td className="mono" style={{ fontSize: 12.5, whiteSpace: "nowrap" }}>{r.taps ?? "-"}</td>
                      {g.choices.length > 0 && (
                        <td>
                          {can && (
                            <select className="input" value={choice[k] ?? ""} style={{ padding: "4px 8px", fontSize: 13 }}
                                    onChange={(e) => setChoice({ ...choice, [k]: e.target.value })}>
                              <option value="">Pilih…</option>
                              {g.choices.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                            </select>
                          )}
                          {r.balance_left !== undefined && (
                            <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 2 }}>Sisa cuti di SeeGaji: {r.balance_left} hari</div>
                          )}
                        </td>
                      )}
                      {g.actionable && <td style={{ fontSize: 12.5, fontWeight: 700, color: STATE[r.state].color }}>{STATE[r.state].text}</td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {g.actionable && todo.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12 }}>
              <button className="btn-rust" disabled={busy || chosen.length === 0 || missing}
                      onClick={() => onApply(g, chosen.map((r) => ({ row: r, choice: choice[key(r)] ?? "" })))}
                      style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />} Terapkan {chosen.length} catatan
              </button>
              {missing && <span style={{ fontSize: 12.5, color: "var(--hazard-dark)" }}>Pilih dulu untuk setiap baris yang dicentang.</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function CatatanPage() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [data, setData] = useState<NoteDecisions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setData(await noteDecisionApi.get(month)); setError(null); }
    catch (err) { setError(readErrors(err).summary); }
  }, [month]);
  useEffect(() => { setData(null); load(); }, [load]);

  const apply = async (g: NoteGroup, items: { row: NoteRow; choice: string }[]) => {
    if (!data) return;
    setBusy(true); setError(null); setDone(null);
    try {
      const res = await noteDecisionApi.apply({ month: data.month, group: g.key,
        items: items.map(({ row, choice }) => ({ employee: row.employee.id, date: row.date, choice })) });
      setData(res);
      const errs = res.errors ?? [];
      setDone(`${g.label}: ${res.applied ?? 0} catatan diterapkan.` +
              (errs.length ? ` ${errs.length} gagal: ` + errs.slice(0, 6).map((e) => `${e.name} ${day(e.date)} (${e.message})`).join("; ") : "") +
              " Hitung ulang payroll periode ini supaya angkanya ikut berubah.");
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Catatan HR → keputusan</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14, maxWidth: 760 }}>
            Catatan dari file rekap (UL, izin, cuti, mati lampu) dikelompokkan menurut artinya. Periksa satu kelompok,
            lalu terapkan sekaligus.{" "}
            <Link href="/dashboard/absensi/tinjau/periode" style={{ color: "var(--rust)" }}>← Tinjau per periode</Link>
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button className="btn-ghost" disabled={!data} onClick={() => data && setMonth(data.prev)} style={{ padding: "6px 8px" }} aria-label="Periode sebelumnya"><ChevronLeft size={16} /></button>
          <div style={{ textAlign: "center", minWidth: 150 }}>
            <div style={{ fontWeight: 700 }}>{data ? `Periode ${data.label}` : "…"}</div>
            {data && <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{day(data.start)} – {day(data.end)}</div>}
          </div>
          <button className="btn-ghost" disabled={!data} onClick={() => data && setMonth(data.next)} style={{ padding: "6px 8px" }} aria-label="Periode berikutnya"><ChevronRight size={16} /></button>
        </div>
      </div>

      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</div>}
      {done && <div className="card" style={{ color: "var(--workshop)", fontWeight: 600, marginBottom: 12 }}>{done}</div>}
      {!data ? (
        <div className="card" style={{ color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
      ) : data.total === 0 ? (
        <div className="card" style={{ color: "var(--steel)", fontSize: 14 }}>
          Belum ada catatan HR di periode ini. Catatan masuk lewat import catatan dari file rekap HR.
        </div>
      ) : (
        data.groups.filter((g) => g.rows.length > 0).map((g) => <GroupCard key={g.key} g={g} busy={busy} onApply={apply} />)
      )}
    </div>
  );
}
