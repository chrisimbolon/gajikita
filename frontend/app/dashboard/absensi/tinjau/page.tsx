"use client";
// =============================================================================
// /dashboard/absensi/tinjau — Perlu Tinjau as a guided checklist: "Siap gajian?" (G17-7, 16 Nov 2026).
// Late arrivals, early leaving and one-tap days are FACTS fined by the company's rules; they are shown per
// person with "what happens if you do nothing" and a button for the exceptions (Maafkan / Tugas luar).
// Only overtime (money out, the SPL) and patterns (many people missing taps = a power cut?) need a decision.
// Every action shows Urungkan. Payroll never waits for this page: open steps simply follow the rules.
// The old day-by-day queue lives at /dashboard/absensi/tinjau/harian; the full table at .../periode.
// G17-7.1: people who (almost) never tap completely are asked once ("Tidak wajib absen?") and left out of the
// power-cut pattern; a missing late fine or ½-day rule says so and links to Pengaturan payroll.
// G17-7.2: someone who stopped tapping is asked "Sudah keluar?" (fills Tanggal keluar); days after the last tap
// in the data are "not imported yet"; Kejadian from a suggestion confirm their own length.
// G20-2: step "Tidak cocok": days where two things can't both be true (a tap or uang makan on a leave day,
// overtime on a leave / absent day, ½ day cut with overtime paid). Fix the data, or "Sudah benar".
// =============================================================================
import FingerprintImport from "@/components/FingerprintImport";
import OvertimeImport from "@/components/OvertimeImport";                       // G17-8
import { attendanceApi, BulkDecideResult, minutesText } from "@/lib/api/attendance";
import { Checklist, CkConflictPerson, CkLatePerson, CkMissingPerson, CkOvertimePerson, checklistApi } from "@/lib/api/checklist";
import { eventApi } from "@/lib/api/events";
import { exemptionApi } from "@/lib/api/exemptions";
import { hrApi, readErrors } from "@/lib/api/hr";
import { rupiah } from "@/lib/format";
import { hoursText, parseHours } from "@/lib/overtimeInput";
import { AlertTriangle, ArrowRight, Ban, Briefcase, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Circle,
         Loader2, Undo2, Wallet, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";

const MON = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const dayText = (iso: string) => `${Number(iso.slice(8, 10))} ${MON[Number(iso.slice(5, 7)) - 1]}`;
const rangeText = (a: string, b: string) => (a === b ? dayText(a) : `${dayText(a)} – ${dayText(b)}`);
const taps = (i: string | null, o: string | null) => (i || o ? `${i ?? "–"} – ${o ?? "–"}` : "tanpa tap");
const halves = (n: number) => { const w = Math.floor(n / 2); return `${w || ""}${n % 2 ? "½" : ""}` || "0"; };   // G13-4: 1 -> ½, 3 -> 1½

type State = "done" | "todo" | "rule";
type Act = (body: { action: "pay_overtime" | "no_overtime" | "forgive" | "away"; ids: string[]; note?: string;
                    overtime?: Record<string, number> }, text: (r: BulkDecideResult) => string) => Promise<boolean>;

function StepIcon({ state }: { state: State }) {
  if (state === "done") return <CheckCircle2 size={22} style={{ color: "var(--workshop)", flexShrink: 0 }} />;
  if (state === "todo") return <AlertTriangle size={22} style={{ color: "var(--hazard-dark)", flexShrink: 0 }} />;
  return <Circle size={22} style={{ color: "var(--steel)", flexShrink: 0 }} />;
}

function Step({ n, state, title, summary, ifNothing, children, open, onToggle, actions }: {
  n: number; state: State; title: string; summary: ReactNode; ifNothing?: string; children?: ReactNode;
  open?: boolean; onToggle?: () => void; actions?: ReactNode;
}) {
  return (
    <div className="card" style={{ padding: 0, marginBottom: 12, borderColor: state === "todo" ? "var(--hazard-dark)" : undefined }}>
      <div style={{ display: "flex", gap: 14, padding: "16px 18px", alignItems: "flex-start" }}>
        <StepIcon state={state} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 800, fontSize: 16 }}>{n}. {title}</div>
          <div style={{ fontSize: 14, marginTop: 2 }}>{summary}</div>
          {ifNothing && <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 4 }}>Kalau dibiarkan: {ifNothing}</div>}
          {actions && <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>{actions}</div>}
        </div>
        {onToggle && (
          <button className="btn-ghost" onClick={onToggle} style={{ display: "flex", alignItems: "center", gap: 4, padding: "5px 10px", fontSize: 13 }}>
            {open ? "Tutup" : "Lihat per orang"} <ChevronDown size={14} style={{ transform: open ? "rotate(180deg)" : undefined }} />
          </button>
        )}
      </div>
      {open && children && <div style={{ padding: "0 18px 16px 54px" }}>{children}</div>}
    </div>
  );
}

function Who({ name, no, right, open, onClick }: { name: string; no: string; right: ReactNode; open: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{ width: "100%", display: "flex", alignItems: "center", gap: 10, background: open ? "var(--paper)" : "none",
                                       border: 0, borderTop: "1px solid var(--line)", padding: "10px 6px", cursor: "pointer", textAlign: "left" }}>
      <ChevronRight size={14} style={{ transform: open ? "rotate(90deg)" : undefined, color: "var(--steel)" }} />
      <span style={{ fontWeight: 700 }}>{name}</span><span className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>{no}</span>
      <span style={{ marginLeft: "auto", fontSize: 13.5 }}>{right}</span>
    </button>
  );
}

/** Late / one-tap days of one person: tick the ones with a reason, then Maafkan or Tugas luar. */
function Exceptions({ rows, act, busy }: {
  rows: { id: string; date: string; text: ReactNode; money: ReactNode; note: string | null; forgiven: boolean }[];
  act: Act; busy: boolean;
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<null | "forgive" | "away">(null);
  const [note, setNote] = useState("");
  const open = rows.filter((r) => !r.forgiven);
  const toggle = (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const go = () => act({ action: mode!, ids: Array.from(picked), note: note.trim() },
                       (r) => mode === "away" ? `${r.decided} hari ditandai tugas luar (dihitung hadir penuh)` : `${r.decided} hari dimaafkan (tanpa potongan)`)
    .then((ok) => { if (ok) { setPicked(new Set()); setMode(null); setNote(""); } });
  return (
    <div style={{ padding: "4px 0 10px 24px" }}>
      <table className="data-table" style={{ fontSize: 13 }}>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} style={{ opacity: r.forgiven ? 0.55 : 1 }}>
              <td style={{ width: 30 }}>{!r.forgiven && <input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} />}</td>
              <td style={{ whiteSpace: "nowrap" }}>{dayText(r.date)}</td>
              <td>{r.text}{r.note && <div style={{ fontSize: 12, color: "var(--steel)" }}>Catatan HR: {r.note}</div>}</td>
              <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{r.forgiven ? "dimaafkan" : r.money}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {open.length > 0 && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
          <button className="btn-ghost" style={{ padding: "4px 10px", fontSize: 12.5 }}
                  onClick={() => setPicked(picked.size === open.length ? new Set() : new Set(open.map((r) => r.id)))}>
            {picked.size === open.length ? "Batal pilih" : "Pilih semua"}
          </button>
          <button className="btn-ghost" disabled={!picked.size} onClick={() => setMode("forgive")} style={{ padding: "4px 10px", fontSize: 12.5 }}>
            Maafkan {picked.size || ""} hari…</button>
          <button className="btn-ghost" disabled={!picked.size} onClick={() => setMode("away")} style={{ padding: "4px 10px", fontSize: 12.5, display: "flex", alignItems: "center", gap: 4 }}>
            <Briefcase size={13} /> Tugas luar…</button>
          {mode && (
            <>
              <input className="input" autoFocus value={note} onChange={(e) => setNote(e.target.value)} style={{ width: 260, padding: "4px 8px", fontSize: 13 }}
                     placeholder={mode === "away" ? "Tugas apa? mis. Belanja alat (wajib)" : "Alasan, mis. izin atasan (opsional)"} />
              <button className="btn-rust" disabled={busy || (mode === "away" && note.trim().length < 3)} onClick={go} style={{ padding: "5px 12px", fontSize: 13 }}>
                {mode === "away" ? `Tandai ${picked.size} hari tugas luar` : `Maafkan ${picked.size} hari`}</button>
              <button className="btn-ghost" onClick={() => setMode(null)} style={{ padding: "4px 10px", fontSize: 12.5 }}>Batal</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function OvertimePerson({ p, cap, act, busy }: { p: CkOvertimePerson; cap: number | null; act: Act; busy: boolean }) {
  const [box, setBox] = useState<Record<string, string>>(() => Object.fromEntries(p.days.map((d) => [d.day_id, hoursText(d.suggested)])));
  const minutes = p.days.map((d) => parseHours(box[d.day_id] ?? ""));
  const bad = minutes.some((m) => m === null);
  const total = minutes.reduce<number>((s, m) => s + (m ?? 0), 0);
  const ids = p.days.map((d) => d.day_id);
  return (
    <div style={{ padding: "4px 0 10px 24px" }}>
      <table className="data-table" style={{ fontSize: 13 }}>
        <thead><tr><th>Tanggal</th><th>Jam absen</th><th>Usulan absen</th><th>Lembur dibayar</th></tr></thead>
        <tbody>
          {p.days.map((d, i) => (
            <tr key={d.day_id}>
              <td style={{ whiteSpace: "nowrap" }}>{dayText(d.date)}{d.rest_day ? " · libur" : ""}</td>
              <td className="mono" style={{ whiteSpace: "nowrap" }}>{taps(d.in, d.out)}
                {d.note && <div style={{ fontSize: 12, color: "var(--steel)", fontFamily: "inherit" }}>Catatan HR: {d.note.text || d.note.code}</div>}</td>
              <td style={{ whiteSpace: "nowrap" }}>{minutesText(d.proposed)}</td>
              <td style={{ whiteSpace: "nowrap" }}>
                <input className="input" inputMode="decimal" value={box[d.day_id] ?? ""} onChange={(e) => setBox({ ...box, [d.day_id]: e.target.value })}
                       style={{ width: 64, padding: "3px 8px", fontSize: 13, ...(minutes[i] === null ? { borderColor: "var(--danger)" } : {}) }} /> jam
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8, alignItems: "center" }}>
        <button className="btn-rust" disabled={busy || bad} style={{ padding: "5px 12px", fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}
                onClick={() => act({ action: "pay_overtime", ids, overtime: Object.fromEntries(p.days.map((d, i) => [d.day_id, minutes[i] ?? 0])) },
                                   (r) => `${p.employee.full_name}: lembur ${minutesText(r.overtime_minutes)} dibayar (${r.decided} hari)`)}>
          <Wallet size={14} /> Bayar lembur · {minutesText(total)}</button>
        <button className="btn-ghost" disabled={busy} style={{ padding: "5px 12px", fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}
                onClick={() => act({ action: "no_overtime", ids }, (r) => `${p.employee.full_name}: ${r.decided} hari hadir, tanpa lembur`)}>
          <Ban size={14} /> Hadir, tanpa lembur</button>
        {bad && <span style={{ fontSize: 12.5, color: "var(--danger)" }}>Tulis jam seperti 2, 2,5 atau 1:30 (0 = tanpa lembur).</span>}
        {cap != null && <span style={{ fontSize: 12, color: "var(--steel)" }}>Usulan dibatasi {cap} menit per hari kerja (Pengaturan payroll).</span>}
      </div>
    </div>
  );
}

export default function SiapGajianPage() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [data, setData] = useState<Checklist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ text: string; batch: string | null } | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [person, setPerson] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [otImport, setOtImport] = useState(false);                                // G17-8
  const [reason, setReason] = useState<Record<string, string>>({});
  const [why, setWhy] = useState<Record<string, string>>({});                     // G17-7.1: per person
  const [leftOn, setLeftOn] = useState<Record<string, string>>({});               // G17-7.2: Tanggal keluar

  const load = useCallback(async () => {
    try { setData(await checklistApi.get(month)); setError(null); }
    catch (err) { setError(readErrors(err).summary); }
  }, [month]);
  useEffect(() => { setData(null); setOpen({}); setPerson(null); load(); }, [load]);

  const act: Act = async (body, text) => {
    setBusy(true); setError(null);
    try {
      const r = await attendanceApi.bulkDecide({ waive_late: false, note: "", ...body });
      const skipped = r.skipped ? ` · ${r.skipped} dilewati` + ((r.skipped_list ?? []).length ? ` (${(r.skipped_list ?? []).slice(0, 2).map((s) => `${s.name} ${dayText(s.date)}: ${s.message}`).join("; ")})` : "") : "";
      setDone({ text: text(r) + skipped, batch: r.batch ?? null });
      await load();
      return true;
    } catch (err) { setError(readErrors(err).summary); return false; }
    finally { setBusy(false); }
  };
  const undo = async () => {
    if (!done?.batch) return;
    setBusy(true);
    try { const r = await attendanceApi.undoBulk(done.batch); setDone({ text: `Diurungkan: ${r.undone} hari kembali seperti sebelumnya`, batch: null }); await load(); }
    catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };
  const makeEvent = async (s: { start: string; end: string }) => {
    const why = (reason[s.start] ?? "").trim();
    setBusy(true); setError(null);
    try {
      await eventApi.create({ start: s.start, end: s.end, kind: "gangguan", reason: why, everyone: true, site_ids: [], employee_ids: [],
                              confirm_long: true });                                // the range is on screen
      setDone({ text: `Kejadian dicatat: ${rangeText(s.start, s.end)} (${why}). Tap yang hilang dimaafkan; terlambat yang tercatat tetap dihitung.`, batch: null });
      await load();
    } catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };
  const dismiss = async (s: { start: string; end: string }) => {
    setBusy(true);
    try { await checklistApi.dismiss(s.start, s.end); setDone({ text: `${rangeText(s.start, s.end)}: bukan kejadian. Tidak ditanyakan lagi.`, batch: null }); await load(); }
    catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };

  const noTrack = async (employeeId: string, name: string, start: string) => {
    const r = (why[employeeId] ?? "").trim();
    setBusy(true); setError(null);
    try {
      await exemptionApi.create(employeeId, { start, end: null, reason: r });
      setDone({ text: `${name}: tidak wajib absen mulai ${dayText(start)} (${r}). Hari kerjanya dihitung hadir; bisa diakhiri di halaman Karyawan.`, batch: null });
      await load();
    } catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };
  const markLeft = async (employeeId: string, name: string, date: string) => {      // G17-7.2
    setBusy(true); setError(null);
    try {
      await hrApi.updateEmployee(employeeId, { end_date: date });
      setDone({ text: `${name}: tanggal keluar ${dayText(date)}. Hari setelahnya tidak dihitung lagi di payroll.`, batch: null });
      await load();
    } catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };
  const conflictOk = async (employeeId: string, name: string, date: string, kind: string) => {   // G20-2
    setBusy(true); setError(null);
    try {
      await checklistApi.conflictOk(employeeId, date, kind);
      setDone({ text: `${name} ${dayText(date)}: sudah benar. Tidak ditanyakan lagi.`, batch: null });
      await load();
    } catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };
  const keep = async (employeeId: string, name: string) => {
    setBusy(true);
    try { await checklistApi.keepTracking(employeeId); setDone({ text: `${name}: tetap wajib absen. Tidak ditanyakan lagi.`, batch: null }); await load(); }
    catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };

  if (!data) return error ? <div className="card" style={{ color: "var(--danger)" }}>{error}</div>
                          : <div style={{ padding: 24 }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>;

  const fine = Number(data.rules.late_fine_per_minute);
  const st = {
    import: (data.import.days > 0 ? "done" : "todo") as State,
    events: (data.events.suggestions.length ? "todo" : "done") as State,
    track: (data.no_track.length ? "todo" : "done") as State,
    notes: (data.notes && data.notes.todo > 0 ? "todo" : "done") as State,
    overtime: (data.overtime.open_days ? "todo" : "done") as State,
    missing: (data.missing.days ? "rule" : "done") as State,
    late: (data.late.count ? "rule" : "done") as State,
    conflicts: (data.conflicts.days ? "todo" : "done") as State,                     // G20-2
  };
  const steps = data.notes ? 8 : 7;
  const settled = Object.entries(st).filter(([k, v]) => (k !== "notes" || data.notes) && v !== "todo").length;
  const togglePerson = (k: string) => setPerson(person === k ? null : k);
  let n = 0;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Siap gajian?</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14, maxWidth: 760 }}>
            Ikuti langkahnya dari atas. Yang tidak diubah mengikuti aturan perusahaan, jadi payroll tetap bisa dihitung.{" "}
            <Link href="/dashboard/absensi/tinjau/harian" style={{ color: "var(--rust)" }}>Antrean harian</Link>
            {" · "}<Link href="/dashboard/absensi/tinjau/periode" style={{ color: "var(--rust)" }}>Tabel lengkap per periode</Link>
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button className="btn-ghost" onClick={() => setMonth(data.prev)} style={{ padding: "6px 8px" }} aria-label="Periode sebelumnya"><ChevronLeft size={16} /></button>
          <div style={{ minWidth: 190, textAlign: "center" }}>
            <div style={{ fontWeight: 800 }}>Periode {data.label}</div>
            <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{rangeText(data.start, data.end)}</div>
          </div>
          <button className="btn-ghost" onClick={() => setMonth(data.next)} style={{ padding: "6px 8px" }} aria-label="Periode berikutnya"><ChevronRight size={16} /></button>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <div style={{ flex: 1, maxWidth: 360, height: 8, background: "var(--paper-3)", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ width: `${(settled / steps) * 100}%`, height: "100%", background: "var(--workshop)" }} />
        </div>
        <span style={{ fontSize: 13.5, fontWeight: 700 }}>{settled} dari {steps} langkah beres</span>
      </div>

      {done && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12, background: "var(--workshop-lt)", color: "var(--workshop)", fontWeight: 700, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <CheckCircle2 size={16} /><span style={{ flex: 1, minWidth: 200 }}>{done.text}</span>
          {done.batch && <button className="btn-ghost" disabled={busy} onClick={undo} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 12px", fontSize: 13, color: "var(--midnight)" }}><Undo2 size={14} /> Urungkan</button>}
          <button onClick={() => setDone(null)} aria-label="Tutup" style={{ background: "none", border: "none", color: "inherit" }}><X size={15} /></button>
        </div>
      )}
      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      <Step n={++n} state={st.import} title="File mesin"
            summary={data.import.days ? <><b>{data.import.days} hari kerja</b> · {data.import.people} dari {data.import.employees} karyawan punya tap
                       {data.import.last_import ? ` · import terakhir ${dayText(data.import.last_import.slice(0, 10))} ${data.import.last_import.slice(11, 16)}` : ""}
                       {data.import.short && <div style={{ fontSize: 13, color: "var(--hazard-dark)", marginTop: 2 }}>
                         Tap terakhir di data: {dayText(data.import.until)}. Hari setelahnya belum dihitung sampai file berikutnya diimport.</div>}</>
                     : "Belum ada tap di periode ini."}
            actions={<button className="btn-ghost" onClick={() => setImporting(true)} style={{ padding: "5px 12px", fontSize: 13 }}>Import file mesin</button>} />

      <Step n={++n} state={st.events} title="Ada kejadian?"
            summary={data.events.suggestions.length
              ? <>Di tanggal ini banyak orang tidak tap atau hanya tap sekali. Mati lampu atau mesin rusak?</>
              : <>Tidak ada tanda gangguan absen.{data.events.existing.length ? " Sudah dicatat: " + data.events.existing.map((e) => `${rangeText(e.start, e.end)} ${e.reason}`).join(", ") : ""}</>}
            ifNothing={data.events.suggestions.length ? "tiap orang dipotong sesuai aturan (tidak hadir / ½ hari)." : undefined}>
      </Step>
      {data.events.suggestions.map((s) => (
        <div key={s.start} className="card" style={{ margin: "-6px 0 12px 54px", padding: "12px 16px" }}>
          <div style={{ fontWeight: 700 }}>{rangeText(s.start, s.end)}: {s.people} orang
            <span style={{ fontWeight: 500, color: "var(--steel)" }}> · {s.absent ? `${s.absent}× tidak tap` : ""}{s.absent && s.one_tap ? ", " : ""}{s.one_tap ? `${s.one_tap}× tap sekali` : ""}</span></div>
          <div style={{ fontSize: 13, color: "var(--steel)" }}>{s.names.join(", ")}{s.people > s.names.length ? ", …" : ""}</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8, alignItems: "center" }}>
            <input className="input" value={reason[s.start] ?? ""} onChange={(e) => setReason({ ...reason, [s.start]: e.target.value })}
                   placeholder="Apa yang terjadi? mis. Mati lampu" style={{ width: 240, padding: "5px 8px", fontSize: 13 }} />
            <button className="btn-rust" disabled={busy || (reason[s.start] ?? "").trim().length < 3} onClick={() => makeEvent(s)} style={{ padding: "5px 12px", fontSize: 13 }}>
              Ya, catat sebagai Kejadian</button>
            <button className="btn-ghost" disabled={busy} onClick={() => dismiss(s)} style={{ padding: "5px 12px", fontSize: 13 }}>Bukan kejadian</button>
          </div>
          <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 6 }}>Kejadian berlaku untuk semua karyawan; ubah orang atau lokasinya di halaman Kejadian.</div>
        </div>
      ))}

      <Step n={++n} state={st.track} title="Tidak perlu absen, atau sudah keluar?"
            summary={data.no_track.length
              ? <>{[data.no_track.filter((p) => p.kind === "left").length ? `${data.no_track.filter((p) => p.kind === "left").length} orang berhenti tap (sudah keluar?)` : "",
                    data.no_track.filter((p) => p.kind === "notrack").length ? `${data.no_track.filter((p) => p.kind === "notrack").length} orang hampir tidak pernah tap lengkap (kerja di luar, sales, manajer, security?)` : ""]
                   .filter(Boolean).join(" · ")}.</>
              : "Semua karyawan yang wajib absen terlihat tap seperti biasa."}
            ifNothing={data.no_track.length ? "hari tanpa tap dihitung tidak hadir dan dipotong." : undefined} />
      {data.no_track.filter((p) => p.kind === "left").map((p) => {
        const on = leftOn[p.employee.id] ?? p.last_tap!;
        return (
          <div key={p.employee.id} className="card" style={{ margin: "-6px 0 12px 54px", padding: "12px 16px" }}>
            <div style={{ fontWeight: 700 }}>{p.employee.full_name} <span className="mono" style={{ fontSize: 12, color: "var(--steel)", fontWeight: 400 }}>{p.employee.employee_no}</span>
              <span style={{ fontWeight: 500, color: "var(--steel)" }}> · tap terakhir {dayText(p.last_tap!)}, lalu {p.missing_after} hari kerja tanpa tap. Sudah keluar?</span></div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8, alignItems: "center" }}>
              <label style={{ fontSize: 13 }}>Tanggal keluar</label>
              <input className="input" type="date" value={on} onChange={(e) => setLeftOn({ ...leftOn, [p.employee.id]: e.target.value })}
                     style={{ width: 160, padding: "5px 8px", fontSize: 13 }} />
              <button className="btn-rust" disabled={busy || !on} onClick={() => markLeft(p.employee.id, p.employee.full_name, on)} style={{ padding: "5px 12px", fontSize: 13 }}>
                Ya, keluar per {on ? dayText(on) : "…"}</button>
              <button className="btn-ghost" disabled={busy} onClick={() => keep(p.employee.id, p.employee.full_name)} style={{ padding: "5px 12px", fontSize: 13 }}>
                Bukan, masih bekerja</button>
            </div>
            <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 6 }}>Tanggal keluar = hari kerja terakhirnya; hari setelahnya tidak dibayar dan tidak dihitung tidak hadir. Masih bekerja tapi cuti panjang? Catat di Cuti & Izin.</div>
          </div>
        );
      })}
      {data.no_track.filter((p) => p.kind === "notrack").map((p) => (
        <div key={p.employee.id} className="card" style={{ margin: "-6px 0 12px 54px", padding: "12px 16px" }}>
          <div style={{ fontWeight: 700 }}>{p.employee.full_name} <span className="mono" style={{ fontSize: 12, color: "var(--steel)", fontWeight: 400 }}>{p.employee.employee_no}</span>
            <span style={{ fontWeight: 500, color: "var(--steel)" }}> · tap lengkap {p.complete} dari {p.expected} hari kerja{p.tapped > p.complete ? `, tap sekali ${p.tapped - p.complete} hari` : ""}</span></div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8, alignItems: "center" }}>
            <input className="input" value={why[p.employee.id] ?? ""} onChange={(e) => setWhy({ ...why, [p.employee.id]: e.target.value })}
                   placeholder="Kenapa? mis. Sales, Kerja di Lobam" style={{ width: 240, padding: "5px 8px", fontSize: 13 }} />
            <button className="btn-rust" disabled={busy || (why[p.employee.id] ?? "").trim().length < 3}
                    onClick={() => noTrack(p.employee.id, p.employee.full_name, p.start)} style={{ padding: "5px 12px", fontSize: 13 }}>
              Tidak wajib absen mulai {dayText(p.start)}</button>
            <button className="btn-ghost" disabled={busy} onClick={() => keep(p.employee.id, p.employee.full_name)} style={{ padding: "5px 12px", fontSize: 13 }}>
              Bukan, tetap wajib absen</button>
          </div>
          <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 6 }}>Tidak wajib absen: hari kerjanya dihitung hadir, tanpa denda, lembur atau uang makan dari tap. Bisa diakhiri kapan saja di halaman Karyawan.</div>
        </div>
      ))}

      {data.notes && (
        <Step n={++n} state={st.notes} title="Catatan HR dari Excel"
              summary={data.notes.todo ? <><b>{data.notes.todo} catatan</b> belum diterapkan (UL, izin, cuti, tugas luar…).</> : `Semua ${data.notes.total} catatan sudah diterapkan.`}
              ifNothing={data.notes.todo ? "catatan hanya tampil, gaji tidak ikut berubah." : undefined}
              actions={data.notes.todo ? <Link href="/dashboard/absensi/tinjau/catatan" className="btn-ghost" style={{ padding: "5px 12px", fontSize: 13, textDecoration: "none" }}>Terapkan per kelompok <ArrowRight size={13} style={{ verticalAlign: "-2px" }} /></Link> : undefined} />
      )}

      <Step n={++n} state={st.overtime} title="Lembur"
            summary={data.overtime.open_days
              ? <><b>{data.overtime.open_days} hari</b> dari {data.overtime.people.length} orang menunggu keputusan · usulan dari jam absen {minutesText(data.overtime.proposed)}. Cocokkan dengan SPL.</>
              : <>Semua lembur sudah diputuskan{data.overtime.decided_days ? ` (${data.overtime.decided_days} hari dibayar)` : ""}.</>}
            ifNothing={data.overtime.open_days ? "lembur yang belum diputuskan tidak dibayar." : undefined}
            actions={<button className="btn-ghost" onClick={() => setOtImport(true)} style={{ padding: "5px 12px", fontSize: 13 }}>
                       Ambil lembur dari file rekap</button>}
            open={!!open.overtime} onToggle={data.overtime.open_days ? () => setOpen({ ...open, overtime: !open.overtime }) : undefined}>
        {data.overtime.people.map((p) => (
          <div key={p.employee.id}>
            <Who name={p.employee.full_name} no={p.employee.employee_no} open={person === `ot-${p.employee.id}`} onClick={() => togglePerson(`ot-${p.employee.id}`)}
                 right={<>{p.days.length} hari · usulan <b>{minutesText(p.proposed)}</b></>} />
            {person === `ot-${p.employee.id}` && <OvertimePerson p={p} cap={data.rules.overtime_cap_minutes} act={act} busy={busy} />}
          </div>
        ))}
      </Step>

      <Step n={++n} state={st.missing} title="Lupa tap (tap sekali)"
            summary={data.missing.days
              ? <><b>{data.missing.days} hari</b> dari {data.missing.people.length} orang.{" "}
                  {data.rules.single_tap_half_day ? <>{data.missing.cut_days} hari dipotong ½ hari, ± <b>{rupiah(data.missing.rupiah)}</b>.</>
                    : <>Aturan &quot;tap sekali = potong ½ hari&quot; belum aktif. <Link href="/dashboard/payroll/pengaturan" style={{ color: "var(--rust)" }}>Atur di Pengaturan payroll</Link></>}</>
              : "Tidak ada."}
            ifNothing={data.missing.days ? (data.rules.single_tap_half_day ? "dipotong ½ hari per hari sesuai aturan perusahaan." : "tidak ada potongan.") : undefined}
            open={!!open.missing} onToggle={data.missing.days ? () => setOpen({ ...open, missing: !open.missing }) : undefined}>
        <div style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 6 }}>Buka orangnya, centang hari yang ada alasannya, lalu Maafkan atau Tugas luar.</div>
        {data.missing.people.map((p: CkMissingPerson) => (
          <div key={p.employee.id}>
            <Who name={p.employee.full_name} no={p.employee.employee_no} open={person === `ms-${p.employee.id}`} onClick={() => togglePerson(`ms-${p.employee.id}`)}
                 right={<>{p.days.length} hari{p.cut_days ? <> · dipotong <b>{rupiah(p.rupiah)}</b></> : ""}</>} />
            {person === `ms-${p.employee.id}` && (
              <Exceptions act={act} busy={busy} rows={p.days.map((d) => ({ id: d.day_id, date: d.date, forgiven: d.forgiven,
                text: <>{d.kind} <span className="mono" style={{ color: "var(--steel)" }}>({taps(d.in, d.out)})</span></>,
                money: d.cut ? "½ hari" : "-", note: d.note ? (d.note.text || d.note.code) : null }))} />
            )}
          </div>
        ))}
      </Step>

      <Step n={++n} state={st.late} title="Terlambat & pulang cepat"
            summary={data.late.count
              ? <><b>{data.late.people.filter((p) => p.count).length} orang</b> · {data.late.count} kali · {data.late.minutes} menit
                  {data.late.half_days ? <> · {halves(data.late.half_days)} hari dipotong</> : null}
                  {data.rules.fine_set || data.late.half_days ? <> · <b>{rupiah(data.late.rupiah)}</b></>
                    : <> · denda terlambat belum diatur. <Link href="/dashboard/payroll/pengaturan" style={{ color: "var(--rust)" }}>Atur di Pengaturan payroll</Link></>}</>
              : "Tidak ada yang dipotong."}
            ifNothing={data.late.count ? (data.rules.fine_set
              ? `dipotong sesuai aturan (toleransi ${data.rules.late_tolerance_minutes} menit untuk datang, ${rupiah(fine)}/menit${
                  data.rules.long_late_half_day_minutes ? `; lebih dari ${data.rules.long_late_half_day_minutes} menit = potong ½ hari` : ""}).`
              : "tidak ada potongan, karena denda per menit di Pengaturan payroll masih Rp 0.") : undefined}
            open={!!open.late} onToggle={data.late.people.length ? () => setOpen({ ...open, late: !open.late }) : undefined}>
        <div style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 6 }}>Terlambat adalah fakta: cukup buka orang yang punya alasan (izin, belanja alat, mati lampu).</div>
        {data.late.people.map((p: CkLatePerson) => (
          <div key={p.employee.id}>
            <Who name={p.employee.full_name} no={p.employee.employee_no} open={person === `lt-${p.employee.id}`} onClick={() => togglePerson(`lt-${p.employee.id}`)}
                 right={p.count ? <>{p.count} kali · {p.minutes} menit{p.half_days ? ` · ${halves(p.half_days)} hari` : ""} · <b>{rupiah(p.rupiah)}</b></> : <span style={{ color: "var(--steel)" }}>semua dimaafkan</span>} />
            {person === `lt-${p.employee.id}` && (
              <Exceptions act={act} busy={busy} rows={p.days.map((d) => ({ id: d.day_id, date: d.date, forgiven: d.forgiven,
                text: <>{d.late > data.rules.late_tolerance_minutes ? `Terlambat ${d.late} mnt` : ""}{d.late > data.rules.late_tolerance_minutes && d.early ? " · " : ""}{d.early ? `Pulang cepat ${d.early} mnt` : ""}{" "}
                       <span className="mono" style={{ color: "var(--steel)" }}>({taps(d.in, d.out)})</span></>,
                money: <>{d.half ? `potong ${halves(d.half)} hari` : ""}{d.half && d.charged ? " + " : ""}{d.charged || !d.half ? `${d.charged} mnt` : ""} · {rupiah(d.rupiah)}</>,
                note: d.note ? (d.note.text || d.note.code) : null }))} />
            )}
          </div>
        ))}
      </Step>

      <Step n={++n} state={st.conflicts} title="Tidak cocok"
            summary={data.conflicts.days
              ? <><b>{data.conflicts.days} hari</b> pada {data.conflicts.people.length} orang: dua hal yang tidak mungkin sama-sama benar
                  (masuk padahal cuti, lembur padahal cuti, dipotong ½ hari tapi lembur dibayar).</>
              : "Tidak ada hari yang bertentangan."}
            ifNothing={data.conflicts.days ? "payroll memakai data apa adanya (hari dengan tap dihitung masuk kerja, lembur yang disetujui dibayar)." : undefined}
            open={!!open.conflicts} onToggle={data.conflicts.people.length ? () => setOpen({ ...open, conflicts: !open.conflicts }) : undefined}>
        <div style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 6 }}>
          Perbaiki datanya di Cuti & Izin atau di Antrean harian; kalau memang benar (mis. dipanggil masuk saat cuti), pilih <b>Sudah benar</b>.
        </div>
        {data.conflicts.people.map((p: CkConflictPerson) => (
          <div key={p.employee.id}>
            <Who name={p.employee.full_name} no={p.employee.employee_no} open={person === `cf-${p.employee.id}`}
                 onClick={() => togglePerson(`cf-${p.employee.id}`)} right={<>{p.items.length} hal</>} />
            {person === `cf-${p.employee.id}` && (
              <table className="data-table" style={{ fontSize: 13, margin: "4px 0 10px 24px" }}>
                <tbody>{p.items.map((c) => (
                  <tr key={c.date + c.kind}>
                    <td style={{ whiteSpace: "nowrap" }}>{dayText(c.date)}</td>
                    <td><b>{c.kind_label}</b><div style={{ color: "var(--steel)" }}>{c.text}</div></td>
                    <td style={{ textAlign: "right" }}>
                      <button className="btn-ghost" disabled={busy} style={{ padding: "4px 10px", fontSize: 12.5, whiteSpace: "nowrap" }}
                              onClick={() => conflictOk(p.employee.id, p.employee.full_name, c.date, c.kind)}>Sudah benar</button>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </div>
        ))}
      </Step>

      <div className="card" style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 6 }}>
        <div style={{ flex: 1, minWidth: 240, fontSize: 13.5 }}>
          {settled === steps ? <b>Semua langkah beres.</b> : <>Langkah yang belum beres <b>mengikuti aturan perusahaan</b>; payroll tetap bisa dihitung dan bisa dihitung ulang kapan saja.</>}
        </div>
        <Link href={data.run ? `/dashboard/payroll/run?id=${data.run.id}` : "/dashboard/payroll"} className="btn-rust"
              style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 6 }}>
          {data.run ? `Buka ${data.run.name}` : `Hitung payroll ${data.label}`} <ArrowRight size={15} />
        </Link>
      </div>

      {importing && <FingerprintImport onClose={() => setImporting(false)} onDone={() => load()} />}
      {otImport && <OvertimeImport onClose={() => setOtImport(false)} onDone={() => load()} />}
    </div>
  );
}
