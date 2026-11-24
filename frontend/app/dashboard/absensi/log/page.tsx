"use client";
// =============================================================================
// /dashboard/absensi/log — Log Kehadiran (G20-1, 23 Nov 2026).
// For every attendance item: who, how much, on what basis, at what cost (like the SPL log for overtime).
// Tabs: Terlambat · Pulang cepat · UL / Mangkir · Uang makan (+ a link to the overtime log).
// Read-only: every number is the payroll's own decision for that day; each person says whether the payroll
// line still says the same ("Sama dengan slip"), needs "Hitung ulang", or was corrected by HR on the line.
// =============================================================================
import AbsensiTabs from "@/components/AbsensiTabs";
import {
  AbsentPerson, AttendanceLog, EarlyPerson, LatePerson, LogDay, LogSlip, MealPerson, attendanceLogApi,
} from "@/lib/api/attendanceLog";
import { readErrors } from "@/lib/api/hr";
import { rupiah } from "@/lib/format";
import { AlertTriangle, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Download, Info, Loader2 } from "lucide-react";
import Link from "next/link";
import { CSSProperties, Fragment, ReactNode, useCallback, useEffect, useState } from "react";

type Tab = "late" | "early" | "absent" | "meal";
const TABS: { key: Tab; label: string }[] = [
  { key: "late", label: "Terlambat" }, { key: "early", label: "Pulang cepat" },
  { key: "absent", label: "UL / Mangkir" }, { key: "meal", label: "Uang makan" },
];
const MON = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const dateText = (iso: string) => `${Number(iso.slice(8, 10))} ${MON[Number(iso.slice(5, 7)) - 1]}`;
const periodText = (a: string, b: string) => `${dateText(a)} – ${dateText(b)} ${b.slice(0, 4)}`;
const hint: CSSProperties = { fontSize: 12.5, color: "var(--steel)", marginTop: 3 };
const nowrap: CSSProperties = { whiteSpace: "nowrap" };
const WARN = "#A3261C";
const INFO = "#2563A8";

const BASIS_COLOR: Record<string, string> = {
  taps: "var(--hazard-dark)", hr_time: "var(--hazard-dark)", rule_half: "var(--hazard-dark)",
  tolerance: "var(--steel)", grace: "var(--steel)", night: INFO, forgiven: "#2E7D4F", leave: "var(--midnight)",
  half_leave: "var(--midnight)", not_counted: "var(--steel)",
  none: WARN, unpaid_leave: "var(--midnight)", hr_rejected: "var(--hazard-dark)",
};

function csvCell(v: string | number | null | undefined) {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",;\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function SlipBadge({ slip }: { slip: LogSlip }) {
  if (slip.state === "none") return null;
  const map = {
    same: { text: "Sama dengan slip", color: "#2E7D4F" },
    stale: { text: "Hitung ulang payroll", color: WARN },
    override: { text: "Dikoreksi HR di payroll", color: INFO },
  } as const;
  const s = map[slip.state];
  return <span style={{ fontSize: 12, color: s.color, ...nowrap }}>{s.text}</span>;
}

function Card({ title, value, sub, warn }: { title: string; value: ReactNode; sub?: ReactNode; warn?: boolean }) {
  return (
    <div style={{ flex: "1 1 150px", border: "1px solid var(--line)", borderRadius: 10, padding: "10px 12px",
                  background: warn ? "var(--danger-light)" : "var(--paper, #fff)" }}>
      <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{title}</div>
      <div style={{ fontSize: 20, fontWeight: 800, color: warn ? WARN : "var(--midnight)", ...nowrap }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--steel)" }}>{sub}</div>}
    </div>
  );
}

function Days({ items, kind }: { items: LogDay[]; kind: Tab }) {
  return (
    <table className="data-table" style={{ margin: "4px 0 8px", fontSize: 13 }}>
      <thead><tr>
        <th>Tanggal</th><th>Masuk</th><th>Pulang</th>
        {kind === "late" || kind === "early" ? <><th>Menit</th><th>Dipotong</th></> : null}
        {kind === "meal" ? <th>Makan</th> : null}
        <th>Rupiah</th><th>Dasar</th>
      </tr></thead>
      <tbody>{items.map((d) => (
        <tr key={d.date + d.basis}>
          <td style={nowrap}>{dateText(d.date)}</td>
          <td style={nowrap}>{d.in ?? "-"}</td><td style={nowrap}>{d.out ?? "-"}</td>
          {kind === "late" || kind === "early" ? (
            <><td>{d.minutes}</td><td style={nowrap}>{d.half ? "½ hari" : d.charged ? `${d.charged} menit` : "-"}</td></>
          ) : null}
          {kind === "meal" ? <td style={nowrap}>{d.missed ? "-" : `${d.meals || 0}${d.breakfast ? " + sarapan" : ""}`}</td> : null}
          <td style={nowrap}>{Number(d.amount) ? rupiah(d.amount) : "-"}</td>
          <td style={{ color: d.warn ? WARN : BASIS_COLOR[d.basis] ?? "var(--steel)" }}>
            {d.warn && <AlertTriangle size={12} style={{ verticalAlign: "-1px", marginRight: 3 }} />}{d.label}
          </td>
        </tr>
      ))}</tbody>
    </table>
  );
}

function bonusText(b: { amount: string; lost: boolean } | null) {
  return b && b.lost ? <div style={{ fontSize: 12, color: WARN }}>Tunjangan kehadiran {rupiah(b.amount)} hangus</div> : null;
}

export default function LogKehadiranPage() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [tab, setTab] = useState<Tab>("late");
  const [data, setData] = useState<AttendanceLog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await attendanceLogApi.get(month));
      setError(null);
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setLoading(false);
    }
  }, [month]);
  useEffect(() => { load(); }, [load]);
  const go = (m: string) => { setMonth(m); setOpen({}); };
  const toggle = (id: string) => setOpen((o) => ({ ...o, [id]: !o[id] }));

  const download = () => {
    if (!data) return;
    const people = data[tab].people as { employee: { full_name: string; employee_no: string }; items: LogDay[] }[];
    const head = tab === "meal" ? ["Karyawan", "No.", "Tanggal", "Masuk", "Pulang", "Makan", "Sarapan", "Rupiah", "Dasar"]
      : tab === "absent" ? ["Karyawan", "No.", "Tanggal", "Masuk", "Pulang", "Rupiah", "Dasar"]
      : ["Karyawan", "No.", "Tanggal", "Masuk", "Pulang", "Menit", "Dipotong (menit)", "½ hari", "Rupiah", "Dasar"];
    const rows: (string | number | null | undefined)[][] = [
      [`Log kehadiran: ${TABS.find((t) => t.key === tab)!.label}, periode gaji ${data.label} (${data.start} s/d ${data.end})`],
      [], head,
    ];
    for (const p of people) {
      for (const d of p.items) {
        const common = [p.employee.full_name, p.employee.employee_no, d.date, d.in, d.out];
        if (tab === "meal") rows.push([...common, d.meals ?? 0, d.breakfast ? 1 : 0, d.amount, d.label]);
        else if (tab === "absent") rows.push([...common, d.amount, d.label]);
        else rows.push([...common, d.minutes, d.charged, d.half ? 1 : 0, d.amount, d.label]);
      }
    }
    const blob = new Blob(["﻿" + rows.map((r) => r.map(csvCell).join(",")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `log-${tab}-${data.month}.csv`;
    a.click();
  };

  const row = (id: string, cells: ReactNode, items: LogDay[], cols: number) => (
    <Fragment key={id}>
      <tr onClick={() => toggle(id)} style={{ cursor: "pointer" }}>
        {cells}
        <td style={{ width: 24, color: "var(--steel)" }}>{open[id] ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</td>
      </tr>
      {open[id] && (
        <tr><td colSpan={cols} style={{ background: "var(--paper-2)", padding: "4px 10px" }}>
          <Days items={items} kind={tab} />
        </td></tr>
      )}
    </Fragment>
  );
  const who = (p: { employee: { full_name: string; employee_no: string } }) => (
    <td>{p.employee.full_name}<div style={hint}>{p.employee.employee_no}</div></td>
  );

  const slipLine = (s: { stale: number; override: number }) => {
    if (!data?.run) return <div style={hint}>Belum ada payroll untuk periode ini. Rupiah dihitung dengan aturan payroll.</div>;
    return (
      <div style={hint}>
        Dibandingkan dengan {data.run.name}{data.run.locked ? " (dikunci)" : ""}.
        {s.stale > 0 && <span style={{ color: WARN }}> {s.stale} orang berbeda dengan slip: Hitung ulang payroll.</span>}
        {s.override > 0 && <span style={{ color: INFO }}> {s.override} orang dikoreksi HR di payroll.</span>}
        {s.stale === 0 && s.override === 0 && <span style={{ color: "#2E7D4F" }}> Semua sama dengan slip.</span>}
      </div>
    );
  };

  let body: ReactNode = null;
  if (data && tab === "late") {
    const s = data.late.summary;
    const people = data.late.people;
    body = (
      <>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "10px 0" }}>
          <Card title="Orang terlambat" value={s.people} sub={`${s.days} hari · ${s.minutes} menit`} />
          <Card title="Dipotong" value={rupiah(s.rupiah)}
                sub={`${s.charged_minutes} menit${s.half_days ? ` · ${s.half_days}× ½ hari` : ""}`} />
          <Card title="Dimaafkan HR" value={`${s.forgiven_days} hari`} />
          <Card title="Tunjangan kehadiran hangus" value={rupiah(s.bonus_rupiah)} sub={`${s.bonus_people} orang`} />
          <Card title="Lewat jam masuk (dalam toleransi)" value={`${s.grace_days} hari`} sub={`${s.grace_people} orang · tanpa potongan`} />
          {s.night_days > 0 && (
            <Card title="Boleh masuk siang (lembur malam)" value={`${s.night_days} hari`} sub={`${s.night_people} orang · tanpa potongan`} />
          )}
        </div>
        {slipLine(s)}
        {people.length === 0 ? <div style={{ ...hint, marginTop: 10 }}>Tidak ada yang terlambat di periode ini.</div> : (
          <table className="data-table" style={{ marginTop: 10 }}>
            <thead><tr><th>Karyawan</th><th>Terlambat</th><th>Dipotong</th><th>Rupiah</th><th>Dalam toleransi</th><th>Payroll</th><th /></tr></thead>
            <tbody>{people.map((p: LatePerson) => row(p.employee.id, <>
              {who(p)}
              <td style={nowrap}>{p.days ? `${p.days}× · ${p.minutes} menit` : "-"}
                {p.forgiven_days > 0 && <div style={{ fontSize: 12, color: "#2E7D4F" }}>{p.forgiven_days} dimaafkan</div>}
                {p.night_days > 0 && <div style={{ fontSize: 12, color: INFO }}>{p.night_days}× boleh masuk siang</div>}</td>
              <td style={nowrap}>{p.charged_minutes ? `${p.charged_minutes} menit` : "-"}{p.half_days ? <div style={{ fontSize: 12 }}>{p.half_days}× ½ hari</div> : null}</td>
              <td style={nowrap}>{Number(p.rupiah) ? rupiah(p.rupiah) : "-"}{bonusText(p.bonus)}</td>
              <td style={{ ...nowrap, color: "var(--steel)" }}>{p.grace_days ? `${p.grace_days}× · ${p.grace_minutes} menit` : "-"}</td>
              <td><SlipBadge slip={p.slip} /></td>
            </>, p.items, 7))}</tbody>
          </table>
        )}
      </>
    );
  } else if (data && tab === "early") {
    const s = data.early.summary;
    body = (
      <>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "10px 0" }}>
          <Card title="Orang pulang cepat" value={s.people} sub={`${s.days} hari · ${s.minutes} menit`} />
          <Card title="Dipotong" value={rupiah(s.rupiah)}
                sub={`${s.charged_minutes} menit${s.half_days ? ` · ${s.half_days}× ½ hari` : ""}`} />
          <Card title="Dimaafkan HR" value={`${s.forgiven_days} hari`} />
          <Card title="Tunjangan kehadiran hangus" value={rupiah(s.bonus_rupiah)} sub={`${s.bonus_people} orang`} />
        </div>
        {slipLine(s)}
        {data.early.people.length === 0 ? <div style={{ ...hint, marginTop: 10 }}>Tidak ada yang pulang cepat di periode ini.</div> : (
          <table className="data-table" style={{ marginTop: 10 }}>
            <thead><tr><th>Karyawan</th><th>Pulang cepat</th><th>Dipotong</th><th>Rupiah</th><th>Payroll</th><th /></tr></thead>
            <tbody>{data.early.people.map((p: EarlyPerson) => row(p.employee.id, <>
              {who(p)}
              <td style={nowrap}>{p.days}× · {p.minutes} menit
                {p.forgiven_days > 0 && <div style={{ fontSize: 12, color: "#2E7D4F" }}>{p.forgiven_days} dimaafkan</div>}</td>
              <td style={nowrap}>{p.charged_minutes ? `${p.charged_minutes} menit` : "-"}{p.half_days ? <div style={{ fontSize: 12 }}>{p.half_days}× ½ hari</div> : null}</td>
              <td style={nowrap}>{Number(p.rupiah) ? rupiah(p.rupiah) : "-"}{bonusText(p.bonus)}</td>
              <td><SlipBadge slip={p.slip} /></td>
            </>, p.items, 6))}</tbody>
          </table>
        )}
      </>
    );
  } else if (data && tab === "absent") {
    const s = data.absent.summary;
    body = (
      <>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "10px 0" }}>
          <Card title="Orang" value={s.people} sub={`${s.days} hari tanpa upah`} />
          <Card title="Tanpa keterangan" value={`${s.no_basis_days} hari`} warn={s.no_basis_days > 0}
                sub="tidak ada tap, cuti, atau keputusan HR" />
          <Card title="Tidak dibayar" value={rupiah(s.rupiah)} />
          <Card title="Tunjangan kehadiran hangus" value={rupiah(s.bonus_rupiah)} sub={`${s.bonus_people} orang`} />
        </div>
        {slipLine(s)}
        {data.absent.people.length === 0 ? <div style={{ ...hint, marginTop: 10 }}>Tidak ada hari tanpa upah di periode ini.</div> : (
          <table className="data-table" style={{ marginTop: 10 }}>
            <thead><tr><th>Karyawan</th><th>Hari</th><th>Dasar</th><th>Rupiah</th><th>Payroll</th><th /></tr></thead>
            <tbody>{data.absent.people.map((p: AbsentPerson) => row(p.employee.id, <>
              {who(p)}
              <td style={nowrap}>{p.days} hari</td>
              <td style={{ fontSize: 13 }}>
                {p.no_basis_days > 0 && <div style={{ color: WARN }}><AlertTriangle size={12} style={{ verticalAlign: "-1px" }} /> {p.no_basis_days} tanpa keterangan</div>}
                {p.unpaid_leave_days > 0 && <div>{p.unpaid_leave_days} izin tanpa upah</div>}
                {p.rejected_days > 0 && <div>{p.rejected_days} ditolak HR</div>}
              </td>
              <td style={nowrap}>{Number(p.rupiah) ? rupiah(p.rupiah) : "-"}
                {p.daily_worker && <div style={{ fontSize: 12, color: "var(--steel)" }}>pekerja harian: tidak dibayar</div>}
                {bonusText(p.bonus)}</td>
              <td><SlipBadge slip={p.slip} /></td>
            </>, p.items, 6))}</tbody>
          </table>
        )}
      </>
    );
  } else if (data && tab === "meal") {
    const s = data.meal.summary;
    body = (
      <>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "10px 0" }}>
          <Card title="Orang dapat uang makan" value={s.people} sub={`${s.meals} kali makan · ${s.breakfasts} sarapan`} />
          <Card title="Dibayar" value={rupiah(s.rupiah)}
                sub={`${rupiah(data.rules.meal_allowance)} per makan${Number(data.rules.breakfast_allowance) ? ` · sarapan ${rupiah(data.rules.breakfast_allowance)}` : ""}`} />
          <Card title="Hadir tanpa uang makan" value={`${s.missed_days} hari`} sub="aturan per hari hadir" />
          <Card title="Uang makan di hari cuti" value={`${s.warn_days} hari`} warn={s.warn_days > 0} />
        </div>
        {slipLine(s)}
        {data.meal.people.length === 0 ? <div style={{ ...hint, marginTop: 10 }}>Tidak ada uang makan di periode ini.</div> : (
          <table className="data-table" style={{ marginTop: 10 }}>
            <thead><tr><th>Karyawan</th><th>Aturan</th><th>Makan</th><th>Sarapan</th><th>Rupiah</th><th>Payroll</th><th /></tr></thead>
            <tbody>{data.meal.people.map((p: MealPerson) => row(p.employee.id, <>
              {who(p)}
              <td style={{ fontSize: 13 }}>{p.rule_label}</td>
              <td style={nowrap}>{p.meals}×{p.missed_days > 0 && <div style={{ fontSize: 12, color: "var(--steel)" }}>{p.missed_days} hari hadir tanpa</div>}</td>
              <td style={nowrap}>{p.breakfasts ? `${p.breakfasts}×` : "-"}</td>
              <td style={nowrap}>{Number(p.rupiah) ? rupiah(p.rupiah) : "-"}
                {p.warn_days > 0 && <div style={{ fontSize: 12, color: WARN }}>{p.warn_days} di hari cuti</div>}</td>
              <td><SlipBadge slip={p.slip} /></td>
            </>, p.items, 7))}</tbody>
          </table>
        )}
      </>
    );
  }

  const r = data?.rules;
  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 6, gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Absensi</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14 }}>
            Siapa, berapa, atas dasar apa, dan berapa rupiahnya. Angkanya keputusan payroll untuk tiap hari.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button className="btn-ghost" disabled={!data} onClick={() => data && go(data.prev)} style={{ padding: "6px 8px" }} aria-label="Periode sebelumnya"><ChevronLeft size={16} /></button>
          <div style={{ minWidth: 190, textAlign: "center" }}>
            <div style={{ fontWeight: 800, color: "var(--midnight)" }}>{data ? `Periode ${data.label}` : "…"}</div>
            {data && <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{periodText(data.start, data.end)}</div>}
          </div>
          <button className="btn-ghost" disabled={!data} onClick={() => data && go(data.next)} style={{ padding: "6px 8px" }} aria-label="Periode berikutnya"><ChevronRight size={16} /></button>
          <button className="btn-ghost" disabled={!data} onClick={download}
                  style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 8 }}>
            <Download size={15} /> CSV
          </button>
        </div>
      </div>

      <AbsensiTabs active="log" />

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{
            padding: "6px 14px", fontSize: 13.5, fontWeight: 700, borderRadius: 8, border: "1px solid var(--line)",
            background: tab === t.key ? "var(--midnight-soft)" : "transparent",
            color: tab === t.key ? "var(--midnight)" : "var(--steel)" }}>{t.label}</button>
        ))}
        <Link href="/dashboard/lembur/spl" style={{ fontSize: 13.5, fontWeight: 700, color: "var(--steel)", padding: "6px 10px" }}>
          Lembur → SPL
        </Link>
      </div>

      {r && (tab === "late" || tab === "early") && (
        <div style={{ ...hint, marginTop: 8 }}>
          <Info size={12} style={{ verticalAlign: "-1px" }} />{" "}
          {tab === "late" && <>Terlambat dihitung setelah toleransi shift ({r.shifts.map((s) => `${s.name} ${s.grace_minutes} menit`).join(", ") || "-"}), dari jam masuk shift. </>}
          Denda {rupiah(r.late_fine_per_minute)} per menit setelah toleransi payroll {r.late_tolerance_minutes} menit
          {r.long_late_half_day_minutes ? `; lebih dari ${r.long_late_half_day_minutes} menit = potong ½ hari` : ""}.
        </div>
      )}

      {loading && <div style={{ ...hint, marginTop: 14 }}><Loader2 size={14} style={{ animation: "spin 1s linear infinite", verticalAlign: "-2px" }} /> Memuat…</div>}
      {error && <div style={{ color: WARN, marginTop: 14 }}>{error}</div>}
      {!loading && data && <div className="card" style={{ marginTop: 10 }}>{body}</div>}
    </div>
  );
}
