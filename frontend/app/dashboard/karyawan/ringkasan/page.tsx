"use client";
// =============================================================================
// /dashboard/karyawan/ringkasan?employee=<id>&month=YYYY-MM — Ringkasan Karyawan (G21-1, 25 Nov 2026).
// One person, one period, one page (design G21 v0.1, D66-D68):
//   Uang            what the slip pays and whether it still matches the attendance
//   Ritme bulan ini one coloured tile per day (dots: lembur, makan, perlu dilihat)
//   Perlu dilihat   days HR should look at (read-only; G21-3 adds SeeGaji's suggestions with a button)
//   Hari demi hari  a time bar per day, chips and the day's rupiah
//   Hari terpilih   the facts, "Kenapa begini" (each rule in one sentence) and the day's rupiah; "Ubah / setujui"
//                   opens the same day panel as Harian and Rekap (same endpoints, same audit).
// Every number is the payroll's own decision for that day (payrun.collect_numbers), like the Log.
// =============================================================================
import DayPanel from "@/components/DayPanel";
import type { DayRow } from "@/lib/api/attendance";
import { readErrors } from "@/lib/api/hr";
import { ChipTone, DayKind, RkDay, Ringkasan, ringkasanApi, ringkasanHref } from "@/lib/api/ringkasan";
import { dmy, rupiah } from "@/lib/format";
import { AlertTriangle, ChevronLeft, ChevronRight, Info, Loader2, Pencil } from "lucide-react";
import Link from "next/link";
import { CSSProperties, ReactNode, useCallback, useEffect, useMemo, useState } from "react";

const INK = "#14273A";
const MUTED = "#5B6B7B";
const LINE = "#E3E8EE";
const NAVY = "#173A57";

const KIND_STYLE: Record<DayKind, { bg: string; fg: string; ring?: string }> = {
  present: { bg: "#DDF2E6", fg: "#14532D" },
  late:    { bg: "#FDF1D8", fg: "#6A4400" },
  absent:  { bg: "#FDE7E5", fg: "#8A1A11", ring: "#E8A39C" },
  unpaid:  { bg: "#FBEDEB", fg: "#8A1A11" },
  leave:   { bg: "#D6F0EF", fg: "#0F4F4C" },
  sick:    { bg: "#E4EEFB", fg: "#123E78" },
  event:   { bg: "#E5E9EF", fg: "#36424F" },
  exempt:  { bg: "#E7F1FB", fg: "#173A57" },
  off:     { bg: "#F7F8FA", fg: "#8A97A5" },
  pending: { bg: "#FFFFFF", fg: "#A3AFBB" },
  outside: { bg: "#FFFFFF", fg: "#C3CBD4" },
};
const KIND_ORDER: DayKind[] = ["present", "late", "absent", "unpaid", "leave", "sick", "event", "exempt", "off"];

const TONE: Record<ChipTone, { bg: string; fg: string }> = {
  blue:   { bg: "#E4EEFB", fg: "#123E78" },
  green:  { bg: "#DDF2E6", fg: "#14532D" },
  amber:  { bg: "#FDF1D8", fg: "#6A4400" },
  red:    { bg: "#FDE7E5", fg: "#8A1A11" },
  violet: { bg: "#F1E8FD", fg: "#5A2E99" },
  indigo: { bg: "#D6F0EF", fg: "#0F4F4C" },
  sky:    { bg: "#E7F1FB", fg: "#173A57" },
  slate:  { bg: "#EEF1F5", fg: "#3E4C5A" },
};
const WHY_DOT: Record<string, string> = { Lembur: "#2F6FC8", "Uang": "#D08700", Terlambat: "#D08700", Pulang: "#D08700",
  Tidak: "#C2410C", Hari: "#C2410C", Catatan: "#7B3FC4", Aturan: "#2F6FC8" };

const MON = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const dayText = (iso: string) => `${Number(iso.slice(8, 10))} ${MON[Number(iso.slice(5, 7)) - 1]}`;
const hoursText = (m: number) => {
  const h = Math.floor(m / 60), r = m % 60;
  return h && r ? `${h} j ${r} mnt` : h ? `${h} j` : `${r} mnt`;
};
const signed = (v: string) => (Number(v) > 0 ? `+${rupiah(v)}` : Number(v) < 0 ? `−${rupiah(String(-Number(v)))}` : "Rp 0");

// the time bar: 05:00 to 05:00 the next day
const BAR_FROM = 5 * 60, BAR_SPAN = 24 * 60;
const pct = (m: number) => Math.max(0, Math.min(100, ((m - BAR_FROM) / BAR_SPAN) * 100));

const card: CSSProperties = { background: "#FFFFFF", border: `1px solid ${LINE}`, borderRadius: 18, padding: "16px 18px" };
const h2: CSSProperties = { margin: 0, fontSize: 16, fontWeight: 800, color: INK };

function Chip({ label, tone, size = 11.5 }: { label: string; tone: ChipTone; size?: number }) {
  const t = TONE[tone] ?? TONE.slate;
  return <span style={{ padding: "3px 8px", borderRadius: 999, fontSize: size, fontWeight: 700, background: t.bg, color: t.fg,
                        whiteSpace: "nowrap" }}>{label}</span>;
}

function Tile({ title, value, sub, tone }: { title: string; value: string; sub?: ReactNode;
                                             tone: "plain" | "blue" | "amber" | "red" | "dark" | "green" }) {
  const s = {
    plain: { bg: "#FFFFFF", bd: LINE, t: MUTED, v: INK },
    blue:  { bg: "#E4EEFB", bd: "#C7DAF5", t: "#1D4F94", v: "#123E78" },
    amber: { bg: "#FDF1D8", bd: "#F4D9A3", t: "#7A4F00", v: "#6A4400" },
    red:   { bg: "#FDE7E5", bd: "#F6C4BF", t: "#9B1C12", v: "#8A1A11" },
    green: { bg: "#DDF2E6", bd: "#B9E2C9", t: "#1F6B43", v: "#14532D" },
    dark:  { bg: NAVY, bd: NAVY, t: "#C9D8E6", v: "#FFFFFF" },
  }[tone];
  return (
    <div style={{ flex: tone === "dark" ? "1.3 1 200px" : tone === "red" ? "1.6 1 250px" : "1 1 150px", background: s.bg, border: `1px solid ${s.bd}`,
                  borderRadius: 16, padding: "12px 16px", minWidth: 0 }}>
      <div style={{ fontSize: 12.5, color: s.t, fontWeight: 700 }}>{title}</div>
      <div style={{ fontSize: tone === "dark" ? 24 : 19, fontWeight: 800, marginTop: 3, color: s.v, whiteSpace: "nowrap" }}>{value}</div>
      {sub && <div style={{ fontSize: 11.5, color: s.t, marginTop: 3, lineHeight: 1.4 }}>{sub}</div>}
    </div>
  );
}

function qty(q: string | null, unit: string) {
  if (!q || !Number(q)) return "";
  const n = Number(q);
  return ` · ${String(Math.round(n * 100) / 100).replace(".", ",")} ${unit}`;
}

/** The money row: the slip (or, before payroll, what attendance moves). */
function Money({ data }: { data: Ringkasan }) {
  const m = data.money;
  if (m.source === "attendance") {
    return (
      <div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {m.parts.length === 0 && <Tile title="Dari absensi" value="Rp 0" tone="plain" sub="Tidak ada lembur, uang makan atau potongan." />}
          {m.parts.map((p) => (
            <Tile key={p.group} title={p.label} value={signed(p.amount)}
                  tone={p.group === "overtime" ? "blue" : p.group === "meal" ? "amber" : p.group === "wage" ? "green" : "red"} />
          ))}
        </div>
        <div style={{ fontSize: 12.5, color: MUTED, marginTop: 8 }}>
          <Info size={12} style={{ verticalAlign: "-1px" }} /> Belum ada payroll untuk periode ini: yang tampil hanya bagian dari absensi.
          Gaji pokok, BPJS dan potongan lain muncul setelah payroll dibuat.
        </div>
      </div>
    );
  }
  const find = (code: string) => m.earnings.filter((e) => e.code === code);
  const base = find("base");
  const ot = [...find("overtime"), ...find("overtime_rest_day")];
  const meal = [...find("meal"), ...find("breakfast")];
  const other = m.earnings.filter((e) => !["base", "overtime", "overtime_rest_day", "meal", "breakfast"].includes(e.code));
  const sum = (xs: { amount: string }[]) => String(xs.reduce((a, x) => a + Number(x.amount), 0));
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
      {base.map((e) => <Tile key={e.code} title={e.label + qty(e.quantity, e.unit)} value={rupiah(e.amount)} tone="plain" />)}
      {ot.length > 0 && <Tile title={`+ Lembur${qty(ot[0].quantity, ot[0].unit)}`} value={rupiah(sum(ot))} tone="blue" />}
      {meal.length > 0 && <Tile title={`+ Uang makan · ${data.totals.meals}×${data.totals.breakfasts ? ` · sarapan ${data.totals.breakfasts}×` : ""}`}
                                value={rupiah(sum(meal))} tone="amber" />}
      {other.map((e, i) => <Tile key={`${e.code}-${i}`} title={`+ ${e.label}${qty(e.quantity, e.unit)}`} value={rupiah(e.amount)} tone="plain" />)}
      <Tile title="− Potongan" value={rupiah(m.deductions_total)} tone="red"
            sub={m.deductions.length === 0 ? "Tidak ada" : (
              <span style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 2 }}>
                {m.deductions.map((d, i) => (
                  <span key={i} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span>{d.label.replace(/^Potongan /, "")}{qty(d.quantity, d.unit)}</span>
                    <span style={{ whiteSpace: "nowrap", fontWeight: 700 }}>{rupiah(d.amount)}</span>
                  </span>
                ))}
              </span>)} />
      <Tile title="= Diterima" value={rupiah(m.net)} tone="dark"
            sub={<>Bruto {rupiah(m.gross)}{data.run ? ` · ${data.run.name}${data.run.locked ? " (dikunci)" : ""}` : ""}</>} />
    </div>
  );
}

function SlipCheck({ data }: { data: Ringkasan }) {
  const c = data.money.check;
  if (c.state === "none" || c.state === "same") return null;
  const run = data.run;
  const link = run ? <Link href={`/dashboard/payroll/run?id=${run.id}`} style={{ fontWeight: 800 }}>Buka payroll</Link> : null;
  if (c.state === "stale") {
    return (
      <div style={{ marginTop: 10, background: "#FDE7E5", border: "1px solid #F6C4BF", color: "#8A1A11", borderRadius: 12,
                    padding: "9px 12px", fontSize: 13.5, display: "flex", gap: 8, alignItems: "flex-start" }}>
        <AlertTriangle size={16} style={{ flex: "0 0 auto", marginTop: 1 }} />
        <span>Absensi berubah sejak payroll dihitung ({c.changed.join(", ")}). Slip di atas masih angka lama:
          {" "}<b>Hitung ulang</b> di payroll. {link}</span>
      </div>
    );
  }
  return (
    <div style={{ marginTop: 10, background: "#E4EEFB", border: "1px solid #C7DAF5", color: "#123E78", borderRadius: 12,
                  padding: "9px 12px", fontSize: 13.5 }}>
      <Info size={14} style={{ verticalAlign: "-2px" }} /> HR mengoreksi angka di payroll ({c.fixed.join(", ")}): slip memakai angka HR,
      bukan hitungan absensi. {link}
    </div>
  );
}

function TimeBar({ d, mealAt }: { d: RkDay; mealAt: number | null }) {
  const s = d.shift;
  const parts: ReactNode[] = [];
  if (d.in_min !== null && d.out_min !== null) {
    const workEnd = s && d.overtime_minutes ? Math.min(d.out_min, Math.max(s.end, d.in_min)) : d.out_min;
    parts.push(<span key="w" style={{ position: "absolute", top: 0, bottom: 0, left: `${pct(d.in_min)}%`,
      width: `${Math.max(0.8, pct(workEnd) - pct(d.in_min))}%`, background: "#2E9E63",
      borderRadius: 7 }} />);
    if (d.overtime_minutes && workEnd < d.out_min) {
      parts.push(<span key="o" style={{ position: "absolute", top: 0, bottom: 0, left: `${pct(workEnd)}%`,
        width: `${pct(d.out_min) - pct(workEnd)}%`, background: "#2F6FC8", borderRadius: "0 7px 7px 0" }} />);
    }
  } else {
    for (const [k, m] of [["i", d.in_min], ["o", d.out_min]] as const) {
      if (m !== null) parts.push(<span key={k} style={{ position: "absolute", top: 2, bottom: 2, left: `calc(${pct(m)}% - 5px)`,
                                                        width: 10, borderRadius: 5, background: "#C2410C" }} />);
    }
  }
  return (
    <span style={{ position: "relative", height: 14, borderRadius: 7, background: "#F1F3F6", overflow: "hidden", display: "block" }}>
      {s && <span style={{ position: "absolute", top: 0, bottom: 0, left: `${pct(s.start)}%`, width: `${pct(s.end) - pct(s.start)}%`,
                           background: "#E4E8EE" }} />}
      {parts}
      {mealAt !== null && <span style={{ position: "absolute", top: 0, bottom: 0, left: `${pct(mealAt)}%`, width: 2, background: "#D08700" }} />}
      <span style={{ position: "absolute", top: 0, bottom: 0, left: `${pct(1440)}%`, width: 2, background: NAVY }} />
    </span>
  );
}

function timeText(d: RkDay) {
  if (d.in || d.out) {
    const next = d.out_min !== null && d.out_min >= 1440 ? " (+1)" : "";
    return `${d.in ?? "–"} → ${d.out ?? "–"}${next}${d.worked_minutes ? ` · ${hoursText(d.worked_minutes)}` : ""}`;
  }
  return d.status_label;
}

/** A DayRow the shared day panel can open (it then loads the full day by its id). */
function toDayRow(data: Ringkasan, d: RkDay): DayRow {
  const e = data.employee;
  return {
    employee: { id: e.id, employee_no: e.employee_no, full_name: e.full_name, overtime_eligible: e.overtime_eligible },
    date: d.date, day_id: d.day_id, status: d.status as DayRow["status"], status_label: d.status_label, tags: [],
    first_in: d.in, last_out: d.out, late_minutes: d.late_minutes, early_minutes: 0, worked_minutes: d.worked_minutes,
    overtime_proposed_minutes: d.overtime_open_minutes, overtime_approved_minutes: d.overtime_minutes || null,
    site_minutes: {}, review_reasons: [], needs_review: d.review, decision: d.decision as DayRow["decision"],
    is_locked: d.locked, hr_fixed: d.hr_fixed, hr_note: d.hr_note,
  };
}

function Detail({ data, d, onEdit }: { data: Ringkasan; d: RkDay; onEdit: () => void }) {
  const facts: [string, string, string?][] = [
    ["Masuk", d.in ?? "–"], ["Pulang", d.out ? `${d.out}${d.out_min !== null && d.out_min >= 1440 ? " (+1)" : ""}` : "–"],
    ["Jam kerja", d.worked_minutes ? hoursText(d.worked_minutes) : "–"],
    ["Lembur", d.overtime_minutes ? hoursText(d.overtime_minutes) : "–", d.overtime_minutes ? "#123E78" : undefined],
    ["Makan", d.meals ? `${d.meals}×` : "–", d.meals ? "#6A4400" : undefined],
    ["Telat", d.late_minutes ? `${d.late_minutes} mnt` : "–", d.late_minutes ? "#8A1A11" : undefined],
  ];
  const total = Number(d.rupiah);
  const canEdit = d.kind !== "outside" && d.kind !== "pending";
  return (
    <div style={{ ...card, display: "flex", flexDirection: "column", gap: 14, position: "sticky", top: 16 }}>
      <div>
        <div style={{ fontSize: 12.5, color: MUTED, fontWeight: 600 }}>Hari terpilih</div>
        <h2 style={{ margin: "2px 0 0", fontSize: 20, fontWeight: 800, color: INK }}>{d.dow}, {dmy(d.date)}</h2>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          <Chip label={data.kinds[d.kind] ?? d.kind} tone="slate" size={12} />
          {d.chips.map((c, i) => <Chip key={i} label={c.label} tone={c.tone} size={12} />)}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
        {facts.map(([k, v, fg]) => (
          <div key={k} style={{ background: "#F6F8FA", borderRadius: 12, padding: "8px 10px" }}>
            <div style={{ fontSize: 10.5, color: MUTED, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase" }}>{k}</div>
            <div style={{ fontSize: 15, fontWeight: 800, marginTop: 2, color: fg ?? INK }}>{v}</div>
          </div>
        ))}
      </div>
      <div>
        <div style={{ fontSize: 12.5, fontWeight: 800, marginBottom: 6, color: INK }}>Kenapa begini</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {d.why.length === 0 && <div style={{ fontSize: 13, color: MUTED }}>Tidak ada yang dihitung di hari ini.</div>}
          {d.why.map((w, i) => (
            <div key={i} style={{ display: "flex", gap: 8, fontSize: 13, lineHeight: 1.45, color: "#2B3A49" }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: WHY_DOT[w.split(" ")[0]] ?? "#2E9E63",
                             marginTop: 6, flex: "0 0 auto" }} />
              <span>{w}</span>
            </div>
          ))}
          {d.conflicts.map((c, i) => (
            <div key={`c${i}`} style={{ display: "flex", gap: 8, fontSize: 13, lineHeight: 1.45, color: "#5A2E99" }}>
              <AlertTriangle size={13} style={{ marginTop: 3, flex: "0 0 auto" }} /><span><b>{c.kind_label}:</b> {c.text}</span>
            </div>
          ))}
        </div>
      </div>
      <div style={{ borderTop: "1px dashed #DCE2E9", paddingTop: 12 }}>
        <div style={{ fontSize: 12.5, fontWeight: 800, marginBottom: 6, color: INK }}>Rupiah hari ini</div>
        {d.money.length === 0 && <div style={{ fontSize: 13, color: MUTED }}>Tidak mengubah slip.</div>}
        {d.money.map((m, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, padding: "3px 0" }}>
            <span style={{ color: "#3E4C5A" }}>{m.label}</span>
            <span style={{ fontWeight: 800, color: Number(m.amount) < 0 ? "#8A1A11" : "#14532D" }}>{signed(m.amount)}</span>
          </div>
        ))}
        {d.money.length > 1 && (
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, padding: "5px 0 0", borderTop: `1px solid ${LINE}`, marginTop: 4 }}>
            <b>Jumlah</b><b style={{ color: total < 0 ? "#8A1A11" : "#14532D" }}>{signed(d.rupiah)}</b>
          </div>
        )}
      </div>
      {canEdit && (
        <button className="btn-ghost" onClick={onEdit} disabled={d.locked}
                style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 42 }}>
          <Pencil size={14} /> {d.locked ? "Hari dikunci" : "Ubah jam / setujui di panel hari"}
        </button>
      )}
    </div>
  );
}

export default function RingkasanPage() {
  const [employee, setEmployee] = useState<string | null>(null);
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [data, setData] = useState<Ringkasan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [edit, setEdit] = useState(false);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const e = q.get("employee");
    setMonth(q.get("month") || undefined);
    setEmployee(e);
    if (!e) { setError("Pilih karyawan dulu (dari Log kehadiran, Rekap, Siap gajian? atau Payroll)."); setLoading(false); }
  }, []);

  const load = useCallback(async () => {
    if (!employee) return;
    setLoading(true);
    try {
      const d = await ringkasanApi.get(employee, month);
      setData(d); setError(null);
      window.history.replaceState(null, "", ringkasanHref(d.employee.id, d.month));
    } catch (err) { setError(readErrors(err).summary); }
    finally { setLoading(false); }
  }, [employee, month]);
  useEffect(() => { load(); }, [load]);

  // a new person or period: pick the first day that needs a look, else the last day with taps
  useEffect(() => {
    if (!data) return;
    setPicked((p) => {
      if (p && data.days.some((d) => d.date === p)) return p;
      const first = data.attention[0]?.date;
      const lastWorked = [...data.days].reverse().find((d) => d.in || d.out)?.date;
      return first ?? lastWorked ?? data.days[0]?.date ?? null;
    });
  }, [data]);

  const go = (m: string) => { setMonth(m); setPicked(null); setEdit(false); };
  const pick = (iso: string) => {
    setPicked(iso); setEdit(false);
    document.getElementById(`rk-${iso}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };
  const day = useMemo(() => data?.days.find((d) => d.date === picked) ?? null, [data, picked]);
  const attn = useMemo(() => new Set(data?.attention.map((a) => a.date) ?? []), [data]);
  const mealAt = useMemo(() => {
    const t = data?.rules.meal_late_after;
    return data?.employee.meal_rule === "late_out" && t ? Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5)) : null;
  }, [data]);

  const e = data?.employee;
  const t = data?.totals;
  return (
    <div style={{ color: INK, display: "flex", flexDirection: "column", gap: 16 }}>
      {/* header */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end", justifyContent: "space-between" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12.5, color: MUTED, fontWeight: 700, letterSpacing: "0.06em" }}>RINGKASAN KARYAWAN</div>
          <h1 className="display" style={{ fontSize: 28, margin: "2px 0 4px", textTransform: "none" }}>{e?.full_name ?? "…"}</h1>
          {e && (
            <div style={{ fontSize: 13.5, color: MUTED, display: "flex", flexWrap: "wrap", gap: "4px 12px" }}>
              <span className="mono">{e.employee_no}</span>
              {e.position && <span>{e.position}</span>}
              <span>{e.pay_type_label} · {rupiah(e.base_rate)}{e.pay_type === "daily" ? " / hari" : ""}</span>
              {e.shift && <span>Shift {e.shift.name} {e.shift.start}–{e.shift.end} (toleransi {e.shift.grace_minutes} mnt)</span>}
              <span>Uang makan: {e.meal_rule_label}</span>
            </div>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {data && data.people.length > 1 && (
            <select value={data.employee.id} aria-label="Pilih karyawan"
                    onChange={(ev) => { setEmployee(ev.target.value); setPicked(null); setEdit(false); }}
                    style={{ minHeight: 40, borderRadius: 10, border: `1px solid ${LINE}`, padding: "0 10px", maxWidth: 220 }}>
              {data.people.map((p) => <option key={p.id} value={p.id}>{p.full_name} · {p.employee_no}</option>)}
            </select>
          )}
          <button className="btn-ghost" disabled={!data} onClick={() => data && go(data.prev)} aria-label="Periode sebelumnya"
                  style={{ padding: "8px 10px" }}><ChevronLeft size={16} /></button>
          <div style={{ textAlign: "center", minWidth: 160 }}>
            <div style={{ fontWeight: 800, fontSize: 16 }}>{data ? `Periode ${data.label}` : "…"}</div>
            {data && t && <div style={{ fontSize: 12.5, color: MUTED }}>{dayText(data.start)} – {dayText(data.end)} · {t.working_days} hari kerja</div>}
          </div>
          <button className="btn-ghost" disabled={!data} onClick={() => data && go(data.next)} aria-label="Periode berikutnya"
                  style={{ padding: "8px 10px" }}><ChevronRight size={16} /></button>
        </div>
      </div>

      {loading && !data && <div style={{ color: MUTED }}><Loader2 size={14} style={{ animation: "spin 1s linear infinite", verticalAlign: "-2px" }} /> Memuat…</div>}
      {error && <div style={{ color: "#8A1A11" }}>{error}</div>}

      {data && t && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, opacity: loading ? 0.6 : 1 }}>
          {/* money */}
          <div>
            <Money data={data} />
            <SlipCheck data={data} />
          </div>

          {/* the month in tiles */}
          <div style={card}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
              <h2 style={h2}>Ritme bulan ini</h2>
              <div style={{ fontSize: 12.5, color: MUTED }}>
                Hadir {t.present_days} dari {t.working_days} hari kerja
                {t.absent_days ? ` · tidak hadir ${t.absent_days}` : ""}{t.paid_leave_days ? ` · cuti ${t.paid_leave_days}` : ""}
                {t.late_days ? ` · telat ${t.late_days}×` : ""}{t.overtime_days ? ` · lembur ${hoursText(t.overtime_minutes)}` : ""}
                {t.meals ? ` · makan ${t.meals}×` : ""}
              </div>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {data.days.map((d) => {
                const s = KIND_STYLE[d.kind];
                const on = d.date === picked;
                return (
                  <button key={d.date} type="button" onClick={() => pick(d.date)}
                          aria-label={`${d.dow} ${dmy(d.date)}: ${data.kinds[d.kind] ?? d.kind}`} title={d.status_label}
                          style={{ width: 40, height: 56, borderRadius: 10, padding: 0, cursor: "pointer", background: s.bg, color: s.fg,
                                   border: `2px solid ${on ? NAVY : s.ring ?? (d.kind === "outside" || d.kind === "pending" ? LINE : "transparent")}`,
                                   display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 3 }}>
                    <span style={{ fontSize: 10, fontWeight: 600, opacity: 0.85 }}>{d.dow}</span>
                    <span style={{ fontSize: 14, fontWeight: 800, lineHeight: 1 }}>{d.day}</span>
                    <span style={{ display: "flex", gap: 2, height: 6 }}>
                      {d.overtime_minutes > 0 && <span style={{ width: 6, height: 6, borderRadius: 3, background: "#1D5FB4" }} />}
                      {(d.meals > 0 || d.breakfast) && <span style={{ width: 6, height: 6, borderRadius: 3, background: "#D08700" }} />}
                      {attn.has(d.date) && <span style={{ width: 6, height: 6, borderRadius: 3, background: "#7B3FC4" }} />}
                    </span>
                  </button>
                );
              })}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginTop: 12, fontSize: 12, color: "#3E4C5A" }}>
              {KIND_ORDER.filter((k) => data.days.some((d) => d.kind === k)).map((k) => (
                <span key={k} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 12, height: 12, borderRadius: 4, background: KIND_STYLE[k].bg, border: k === "off" ? `1px solid ${LINE}` : undefined }} />
                  {data.kinds[k]}
                </span>
              ))}
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: 4, background: "#1D5FB4" }} />Lembur</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: 4, background: "#D08700" }} />Uang makan</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: 4, background: "#7B3FC4" }} />Perlu dilihat</span>
            </div>
          </div>

          {/* what to look at */}
          {data.attention.length > 0 && (
            <div style={{ background: "#F5EEFD", border: "1px solid #DCCAF5", borderRadius: 18, padding: "14px 18px",
                          display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <span style={{ minWidth: 28, height: 28, borderRadius: 9, background: "#7B3FC4", color: "#FFFFFF", display: "flex",
                               alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 14, padding: "0 6px" }}>
                  {data.attention.length}</span>
                <h2 style={{ ...h2, color: "#3E1F6B" }}>Perlu dilihat</h2>
                <span style={{ fontSize: 12.5, color: "#5A3D86" }}>Ketuk tanggalnya untuk melihat harinya</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {data.attention.map((a, i) => (
                  <button key={i} type="button" onClick={() => pick(a.date)}
                          style={{ display: "flex", gap: 12, alignItems: "center", textAlign: "left", background: "#FFFFFF",
                                   border: "1px solid #E6DAF8", borderRadius: 12, padding: "9px 12px", cursor: "pointer", color: INK }}>
                    <span style={{ fontWeight: 800, fontSize: 13.5, minWidth: 54 }}>{dayText(a.date)}</span>
                    <span style={{ fontSize: 13.5, flex: 1 }}>{a.text}</span>
                    <ChevronRight size={14} style={{ color: "#5A3D86", flex: "0 0 auto" }} />
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* days + the picked day */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 18, alignItems: "flex-start" }}>
            <div style={{ ...card, flex: "999 1 600px", minWidth: 0, padding: "8px 10px 10px" }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", padding: "8px 8px 10px", borderBottom: "1px solid #EEF1F5" }}>
                <h2 style={{ ...h2, flex: "1 1 auto" }}>Hari demi hari</h2>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11.5, color: "#3E4C5A" }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 14, height: 8, borderRadius: 3, background: "#E4E8EE" }} />Jam shift</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 14, height: 8, borderRadius: 3, background: "#2E9E63" }} />Jam kerja</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 14, height: 8, borderRadius: 3, background: "#2F6FC8" }} />Lembur</span>
                  {mealAt !== null && <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 2, height: 12, background: "#D08700" }} />{data.rules.meal_late_after} uang makan</span>}
                  <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 2, height: 12, background: NAVY }} />00:00</span>
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column" }}>
                {data.days.map((d) => {
                  const on = d.date === picked;
                  const r = Number(d.rupiah);
                  const quiet = d.kind === "off" || d.kind === "outside" || d.kind === "pending";
                  return (
                    <button key={d.date} id={`rk-${d.date}`} type="button" onClick={() => { setPicked(d.date); setEdit(false); }}
                            style={{ display: "grid", gridTemplateColumns: "60px minmax(0, 1fr) 92px", alignItems: "start", gap: "4px 12px",
                                     width: "100%", textAlign: "left",
                                     border: 0, borderBottom: "1px solid #F0F2F5", background: on ? "#EEF3F8" : "transparent", color: INK,
                                     padding: quiet ? "5px 10px" : "9px 10px", borderRadius: 10, cursor: "pointer",
                                     boxShadow: on ? `inset 3px 0 0 ${NAVY}` : undefined, opacity: quiet ? 0.7 : 1 }}>
                      <span style={{ display: "flex", flexDirection: "column" }}>
                        <span style={{ fontWeight: 800, fontSize: 14 }}>{dayText(d.date)}</span>
                        <span style={{ fontSize: 11.5, color: MUTED }}>{d.dow}</span>
                      </span>
                      <span style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4, paddingTop: quiet ? 0 : 2 }}>
                        {!quiet && <TimeBar d={d} mealAt={mealAt} />}
                        <span style={{ fontSize: 12, color: d.in || d.out ? "#2B3A49" : KIND_STYLE[d.kind].fg, fontWeight: 600 }}>
                          {timeText(d) || data.kinds[d.kind]}
                        </span>
                        {(d.chips.length > 0 || d.conflicts.length > 0) && (
                          <span style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                            {d.chips.map((c, i) => <Chip key={i} label={c.label} tone={c.tone} />)}
                            {d.conflicts.length > 0 && <Chip label="Tidak cocok" tone="violet" />}
                          </span>
                        )}
                      </span>
                      <span style={{ textAlign: "right", fontWeight: 800, fontSize: 13.5, whiteSpace: "nowrap",
                                     color: r < 0 ? "#8A1A11" : r > 0 ? "#14532D" : "#A3AFBB" }}>
                        {r ? signed(d.rupiah) : "–"}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div style={{ fontSize: 12, color: MUTED, padding: "10px 8px 2px" }}>
                Rupiah per hari dihitung dengan aturan payroll yang sama, dibulatkan per hari; jumlah yang dibayar tetap angka di slip.
              </div>
            </div>
            <div style={{ flex: "1 1 340px", minWidth: 0 }}>
              {day && edit ? (
                <DayPanel key={`${day.date}-${day.day_id}`} row={toDayRow(data, day)} onChanged={() => load()} onClose={() => setEdit(false)} />
              ) : day ? (
                <Detail data={data} d={day} onEdit={() => setEdit(true)} />
              ) : (
                <div style={{ ...card, color: MUTED, fontSize: 13.5 }}>Pilih tanggal untuk melihat harinya.</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
