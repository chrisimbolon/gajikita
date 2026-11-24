"use client";
// =============================================================================
// /dashboard/absensi/tinjau/periode — Tinjau massal per periode (G11, 4 Nov 2026).
// A whole pay period (26 - 25) of days waiting for HR, filtered by kind (Lembur, Terlambat, Tidak absen
// pulang ...), decided many at once. Click a row to open the day itself.
// G12f.3.2: HR's note from the recap shows in "Kenapa"; "Ada catatan HR" / "Tanpa catatan" filter the list.
// G17-6 (15 Nov 2026) — overtime decided in one place:
//   * every overtime row has a "Lembur dibayar" box (hours, as on the SPL), filled with what the taps propose
//   * "Bayar lembur" pays what the boxes say, "Hadir, tanpa lembur" counts the day without overtime
//   * "Sudah diputuskan" lists the decided days: change the hours there, or "Kembalikan ke belum (tunggu SPL)"
//   * every action can be undone from the green bar ("Urungkan")
//   The old "Batasi lembur per hari kerja" box is gone from here; the company limit stays in Pengaturan payroll.
// =============================================================================
import DayPanel, { StatusPill } from "@/components/DayPanel";
import { HrNoteLine } from "@/components/HrNote";
import { BulkDecideBody, BulkDecideResult, BulkTrimmed, DayRow, ReviewPeriodData, ReviewPeriodRow, attendanceApi, minutesText } from "@/lib/api/attendance";
import { readErrors } from "@/lib/api/hr";
import { hoursText, parseHours } from "@/lib/overtimeInput";
import { dmy } from "@/lib/format";
import { Ban, Briefcase, Check, CheckCircle2, ChevronLeft, ChevronRight, Loader2, RotateCcw, Undo2, Wallet, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

const MON = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
function periodText(start: string, end: string): string {
  const [y1, m1, d1] = start.split("-").map(Number);
  const [y2, m2, d2] = end.split("-").map(Number);
  return `${d1} ${MON[m1 - 1]}${y1 !== y2 ? ` ${y1}` : ""} – ${d2} ${MON[m2 - 1]} ${y2}`;
}
const dayText = (iso: string) => `${Number(iso.slice(8, 10))} ${MON[Number(iso.slice(5, 7)) - 1]}`;

type Mode = null | "approve" | "reject" | "away";   // the actions that need a note or a choice first
type State = "" | "decided";

function trimmedText(list: BulkTrimmed[], total: number): string {                  // G12g
  const shown = list.slice(0, 5).map((t) => `${t.name} ${t.date.slice(8, 10)}-${t.date.slice(5, 7)} (${t.proposed}→${t.approved})`);
  return shown.join(", ") + (total > shown.length ? `, +${total - shown.length} lainnya` : "");
}

function skippedText(r: { skipped: number; skipped_list?: { name: string; date: string; message: string }[] }): string {
  if (!r.skipped) return "";
  const list = (r.skipped_list ?? []).slice(0, 3).map((s) => `${s.name} ${dayText(s.date)}: ${s.message}`);
  return ` · ${r.skipped} dilewati` + (list.length ? ` (${list.join("; ")}${r.skipped > list.length ? "; …" : ""})` : "");
}

/** What the box starts with: decided days show what was approved, open days what the taps propose. */
function startMinutes(r: ReviewPeriodRow, state: State, cap: number | null): number {
  if (state === "decided") return r.overtime_approved_minutes ?? 0;
  const proposed = r.overtime_proposed_minutes || 0;
  const restDay = r.kinds.includes("day_off_work");
  return cap != null && !restDay ? Math.min(proposed, cap) : proposed;
}

export default function TinjauPeriodePage() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [state, setState] = useState<State>("");                        // G17-6
  const [kind, setKind] = useState("");
  const [hasNote, setHasNote] = useState<"" | "1" | "0">("");               // G12f.3.2
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ReviewPeriodData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [allMatching, setAllMatching] = useState(false);
  const [mode, setMode] = useState<Mode>(null);
  const [note, setNote] = useState("");
  const [typed, setTyped] = useState<Record<string, string>>({});       // G17-6: day id -> what HR typed
  const known = useRef(new Map<string, number | null>());                 // day id -> minutes in its box
  const seen = useRef(new Map<string, boolean>());                        // day id -> over 4 h on a working day
  const [waiveLate, setWaiveLate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ text: string; batch: string | null } | null>(null);
  const [open, setOpen] = useState<DayRow | null>(null);

  useEffect(() => { const t = setTimeout(() => { setQuery(q.trim()); setPage(1); }, 350); return () => clearTimeout(t); }, [q]);

  const clearPick = () => { setPicked(new Set()); setAllMatching(false); setMode(null); setWaiveLate(false); };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await attendanceApi.reviewPeriod({ month, kind: kind || undefined, q: query || undefined, page,
                                                   has_note: hasNote || undefined, state: state || undefined });
      setData(d); setError(null);
      d.rows.forEach((r) => { if (r.day_id) seen.current.set(r.day_id, r.over_legal); });
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setLoading(false);
    }
  }, [month, kind, query, page, hasNote, state]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { clearPick(); setTyped({}); }, [month, kind, query, hasNote, state]);

  const rows = data?.rows ?? [];
  const cap = data?.cap_minutes ?? null;
  const boxText = (r: ReviewPeriodRow) => typed[r.day_id!] ?? hoursText(startMinutes(r, state, cap));
  const hasBox = (r: ReviewPeriodRow) => r.decision !== "rejected" && ((r.overtime_proposed_minutes || 0) > 0 || (r.overtime_approved_minutes ?? 0) > 0);
  rows.forEach((r) => { if (r.day_id) known.current.set(r.day_id, hasBox(r) ? parseHours(boxText(r)) : 0); });

  const pageIds = rows.map((r) => r.day_id!).filter(Boolean);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => picked.has(id));
  const count = allMatching ? data?.total ?? 0 : picked.size;
  const pickedIds: string[] = Array.from(picked);
  const invalid = pickedIds.filter((id) => known.current.get(id) === null).length;
  const payTotal: number = pickedIds.reduce((sum: number, id: string) => sum + (known.current.get(id) ?? 0), 0);
  const overCount = allMatching ? data?.over_legal ?? 0 : pickedIds.filter((id) => seen.current.get(id)).length;

  const toggle = (id: string) => {
    setAllMatching(false);
    setPicked((cur) => { const n = new Set(cur); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  };
  const togglePage = () => {
    setAllMatching(false);
    setPicked((cur) => { const n = new Set(cur); pageIds.forEach((id) => (allOnPage ? n.delete(id) : n.add(id))); return n; });
  };

  const run = async (body: BulkDecideBody, text: (r: BulkDecideResult) => string) => {
    if (!data) return;
    setBusy(true); setError(null);
    try {
      const target: Partial<BulkDecideBody> = allMatching ? { month: data.month, kind: kind || "", q: query, has_note: hasNote, state }
                                                          : { ids: pickedIds };
      const r = await attendanceApi.bulkDecide({ ...body, ...target });
      setDone({ text: text(r) + skippedText(r), batch: r.batch ?? null });
      clearPick(); setNote(""); setTyped({});
      setData(null);                      // no stale rows while the list reloads
      await load();
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  const payOvertime = () => {
    const overtime: Record<string, number> = {};
    for (const r of rows) {                 // what the boxes on this page say; other pages: the taps' proposal
      const id = r.day_id!;
      if (!(allMatching || picked.has(id)) || !hasBox(r)) continue;
      const m = parseHours(boxText(r));
      if (m !== null) overtime[id] = m;
    }
    pickedIds.forEach((id) => { const m = known.current.get(id); if (m != null && !(id in overtime)) overtime[id] = m; });
    run({ action: "pay_overtime", note, waive_late: waiveLate, overtime },
        (r) => `${r.decided} hari: lembur dibayar ${minutesText(r.overtime_minutes)}` +
               (r.over_legal_days ? ` · ${r.over_legal_days} hari lembur > 4 jam (peringatan PP 35/2021)` : ""));
  };
  const noOvertime = () => run({ action: "no_overtime", note, waive_late: waiveLate },
                               (r) => `${r.decided} hari: hadir, tanpa lembur`);
  const backToOpen = () => run({ action: "reset", note: "", waive_late: false },
                               (r) => `${r.decided} hari kembali ke "Belum diputuskan" (tunggu SPL): lembur belum dibayar`);
  const decideWithNote = () => {
    if (!mode) return;
    run({ action: mode, note, waive_late: mode === "approve" ? waiveLate : false },
        (r) => `${r.decided} hari ${mode === "approve" ? "disetujui" : mode === "away" ? "ditandai tugas luar (dihitung hadir, tanpa potongan)" : "ditolak"}` +
               (mode === "approve" && waiveLate ? " · terlambat dimaafkan (tanpa denda)" : "") +
               (r.overtime_minutes ? ` · lembur ${minutesText(r.overtime_minutes)}` : "") +
               (r.trimmed_count ? ` · ${r.trimmed_count} hari DIPOTONG ke ${r.cap_minutes} menit (Pengaturan payroll): ${trimmedText(r.trimmed, r.trimmed_count)}` : "") +
               (r.over_legal_days ? ` · ${r.over_legal_days} hari lembur > 4 jam (peringatan PP 35/2021)` : ""));
  };

  const undo = async () => {
    if (!done?.batch) return;
    setBusy(true); setError(null);
    try {
      const r = await attendanceApi.undoBulk(done.batch);
      setDone({ text: `Diurungkan: ${r.undone} hari kembali seperti sebelumnya` + skippedText(r), batch: null });
      setData(null);
      await load();
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  const tab = (s: State, label: string, n: number | undefined) => (
    <button key={s || "open"} onClick={() => { setState(s); setPage(1); }}
            style={{ border: 0, cursor: "pointer", padding: "7px 14px", fontSize: 13.5, fontWeight: 700,
                     background: state === s ? "var(--midnight)" : "transparent", color: state === s ? "#fff" : "var(--midnight)" }}>
      {label}{n != null ? ` (${n})` : ""}
    </button>
  );

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Tinjau per periode</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14 }}>
            Semua hari yang menunggu keputusan HR dalam satu periode gaji. Saring per jenis, centang, lalu putuskan sekaligus.{" "}
            <Link href="/dashboard/absensi/tinjau" style={{ color: "var(--rust)", fontWeight: 700 }}>← Siap gajian?</Link>
            {" · "}<Link href="/dashboard/absensi/tinjau/harian" style={{ color: "var(--rust)" }}>Antrean harian</Link>
            {" · "}
            <Link href="/dashboard/absensi/tinjau/catatan" style={{ color: "var(--rust)", fontWeight: 700 }}>Catatan HR → keputusan</Link>
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button className="btn-ghost" disabled={!data} onClick={() => data && (setMonth(data.prev), setPage(1))} style={{ padding: "6px 8px" }} aria-label="Periode sebelumnya"><ChevronLeft size={16} /></button>
          <div style={{ minWidth: 190, textAlign: "center" }}>
            <div style={{ fontWeight: 800, color: "var(--midnight)" }}>{data ? `Periode ${data.label}` : "…"}</div>
            {data && <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{periodText(data.start, data.end)}</div>}
          </div>
          <button className="btn-ghost" disabled={!data} onClick={() => data && (setMonth(data.next), setPage(1))} style={{ padding: "6px 8px" }} aria-label="Periode berikutnya"><ChevronRight size={16} /></button>
        </div>
      </div>

      {/* G17-6: open or decided */}
      <div style={{ display: "inline-flex", border: "1px solid var(--midnight)", borderRadius: 8, overflow: "hidden", marginBottom: 10 }}>
        {tab("", "Belum diputuskan", data?.pending_all)}
        {tab("decided", "Sudah diputuskan", data?.decided_all)}
      </div>

      {/* kinds = filters */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
        <button className="pill" onClick={() => { setKind(""); setPage(1); }}
                style={{ border: "1px solid var(--line)", cursor: "pointer", padding: "6px 12px", fontSize: 13.5,
                         background: kind === "" ? "var(--ink)" : "var(--paper-3)", color: kind === "" ? "var(--paper)" : "var(--ink)" }}>
          Semua {data ? `(${data.all})` : ""}
        </button>
        {(data?.kinds ?? []).map((k) => (
          <button key={k.key} className="pill" onClick={() => { setKind(k.key); setPage(1); }}
                  style={{ border: "1px solid var(--line)", cursor: "pointer", padding: "6px 12px", fontSize: 13.5,
                           background: kind === k.key ? "var(--ink)" : "var(--paper-3)", color: kind === k.key ? "var(--paper)" : "var(--ink)" }}>
            {k.label} ({k.count})
          </button>
        ))}
        {data && ((data.with_note ?? 0) > 0 || hasNote) && (["1", "0"] as const).map((v) => (
          <button key={v} className="pill" onClick={() => { setHasNote(hasNote === v ? "" : v); setPage(1); }}
                  title="Catatan HR dari file rekap yang diimport"
                  style={{ border: "1px dashed var(--midnight)", cursor: "pointer", padding: "6px 12px", fontSize: 13.5,
                           background: hasNote === v ? "var(--midnight)" : "transparent", color: hasNote === v ? "#fff" : "var(--midnight)" }}>
            {v === "1" ? `Ada catatan HR (${data.with_note ?? 0})` : "Tanpa catatan HR"}
          </button>
        ))}
        <input className="input" placeholder="Cari nama atau no. karyawan" value={q} onChange={(e) => setQ(e.target.value)}
               style={{ width: 240, marginLeft: "auto" }} />
      </div>

      {done && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12, background: "var(--workshop-lt)", color: "var(--workshop)", fontWeight: 700,
                                       display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <CheckCircle2 size={16} /> <span style={{ flex: 1, minWidth: 200 }}>{done.text}</span>
          {done.batch && (
            <button className="btn-ghost" disabled={busy} onClick={undo}
                    style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 12px", fontSize: 13, color: "var(--midnight)" }}>
              <Undo2 size={14} /> Urungkan
            </button>
          )}
          <button onClick={() => setDone(null)} aria-label="Tutup" style={{ background: "none", border: "none", color: "inherit" }}><X size={15} /></button>
        </div>
      )}
      {error && <div className="card" style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      {/* the bulk bar */}
      {count > 0 && (
        <div className="card" style={{ padding: "12px 16px", marginBottom: 12, borderColor: "var(--midnight)", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <b>{count} hari dipilih</b>
            {!allMatching && data && allOnPage && data.total > pageIds.length && (
              <button className="btn-ghost" onClick={() => setAllMatching(true)} style={{ padding: "3px 10px", fontSize: 13 }}>
                Pilih semua {data.total} yang cocok
              </button>
            )}
            {allMatching && <span style={{ fontSize: 13, color: "var(--steel)" }}>(semua yang cocok dengan saringan ini, di semua halaman)</span>}
            <span style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button className="btn-rust" disabled={busy || invalid > 0} onClick={payOvertime} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Wallet size={15} />}
                Bayar lembur{allMatching ? "" : ` · ${minutesText(payTotal)}`}
              </button>
              <button className="btn-ghost" disabled={busy} onClick={noOvertime} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <Ban size={15} /> Hadir, tanpa lembur
              </button>
              {state === "decided" ? (
                <button className="btn-ghost" disabled={busy} onClick={backToOpen} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <RotateCcw size={15} /> Kembalikan ke belum (tunggu SPL)
                </button>
              ) : (
                <>
                  <button className="btn-ghost" onClick={() => setMode(mode === "approve" ? null : "approve")} style={{ display: "flex", alignItems: "center", gap: 6 }}><Check size={15} /> Setujui…</button>
                  <button className="btn-ghost" onClick={() => setMode(mode === "reject" ? null : "reject")} style={{ display: "flex", alignItems: "center", gap: 6 }}><X size={15} /> Tolak…</button>
                  <button className="btn-ghost" onClick={() => setMode(mode === "away" ? null : "away")} style={{ display: "flex", alignItems: "center", gap: 6 }}><Briefcase size={15} /> Tugas luar…</button>
                </>
              )}
              <button className="btn-ghost" onClick={clearPick}>Batal pilih</button>
            </span>
          </div>
          {state === "" && (
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13.5 }}>
              <input type="checkbox" checked={waiveLate} onChange={(e) => setWaiveLate(e.target.checked)} />
              Maafkan terlambat / tap sekali (tanpa potongan) — untuk Bayar lembur, Hadir tanpa lembur dan Setujui
            </label>
          )}
          {invalid > 0 && (
            <div style={{ fontSize: 13, color: "var(--danger)", fontWeight: 600 }}>
              {invalid} kotak &quot;Lembur dibayar&quot; belum benar. Tulis jam seperti 2, 2,5 atau 1:30 (0 = tanpa lembur).
            </div>
          )}
          <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
            <b>Bayar lembur</b>: dibayar sesuai kotak &quot;Lembur dibayar&quot; di tiap baris (ubah dulu bila SPL berbeda).{" "}
            <b>Hadir, tanpa lembur</b>: hari dihitung hadir, lembur tidak dibayar.{" "}
            {state === "decided"
              ? <><b>Kembalikan ke belum</b>: keputusan dibatalkan, hari kembali ke daftar &quot;Belum diputuskan&quot; dan lembur belum dibayar. </>
              : <>Belum yakin (menunggu SPL)? Biarkan saja: lembur yang belum diputuskan tidak dibayar. </>}
            Salah klik? Tekan <b>Urungkan</b> di bar hijau.
          </div>
          {mode && (
            <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", borderTop: "1px solid var(--line)", paddingTop: 10 }}>
              <div style={{ flex: 1, minWidth: 220 }}><label className="label">{mode === "reject" ? "Alasan (wajib)" : mode === "away" ? "Tugas apa? (wajib)" : "Catatan (opsional)"}</label>
                <input className="input" value={note} onChange={(e) => setNote(e.target.value)}
                       placeholder={mode === "reject" ? "mis. titip absen" : mode === "away" ? "mis. Belanja alat lori fuso" : "mis. sesuai SPL bulan ini"} /></div>
              <button className="btn-rust" disabled={busy || ((mode === "reject" || mode === "away") && !note.trim())} onClick={decideWithNote}
                      style={{ display: "flex", alignItems: "center", gap: 6, background: mode === "reject" ? "var(--danger)" : undefined }}>
                {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
                {mode === "approve" ? `Setujui ${count} hari${waiveLate ? " + maafkan terlambat" : ""}`
                  : mode === "away" ? `Tandai ${count} hari tugas luar` : `Tolak ${count} hari`}
              </button>
            </div>
          )}
          {mode === "approve" && (
            <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
              Setujui: terlambat, tidak absen pulang dan alasan lain dianggap beres; lembur ikut disetujui sebesar usulan dari jam absen
              {cap != null ? ` (paling banyak ${cap} menit per hari kerja, sesuai Pengaturan payroll)` : ""}. Untuk menentukan jam lembur
              sendiri, pakai <b>Bayar lembur</b> atau <b>Hadir, tanpa lembur</b>.
            </div>
          )}
          {mode === "reject" && (
            <div style={{ fontSize: 12.5, color: "var(--steel)" }}>Tolak: hari dihitung <b>tidak hadir</b> (atau kembali ke cutinya). Untuk menolak lembur saja, pakai <b>Hadir, tanpa lembur</b>.</div>
          )}
          {mode === "away" && (
            <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
              Tugas perusahaan di luar (mis. belanja alat): hari-hari ini dihitung hadir penuh, tanpa potongan terlambat
              atau ½ hari, dan tanpa lembur atau uang makan otomatis. Tercatat sebagai &quot;Tidak wajib absen&quot; 1 hari
              di halaman Karyawan.
            </div>
          )}
          {overCount > 0 && (
            <div style={{ fontSize: 13, color: "var(--hazard-dark)", fontWeight: 600 }}>
              {overCount} hari lembur lebih dari 4 jam di hari kerja (batas PP 35/2021). Jam yang sudah dikerjakan tetap dibayar; payroll menampilkan peringatannya.
            </div>
          )}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: open ? "minmax(0, 1fr) 460px" : "1fr", gap: 18, alignItems: "start" }}>
        <div className="card" style={{ padding: 0, opacity: loading ? 0.6 : 1, overflowX: "auto" }}>
          {loading && !data ? (
            <div style={{ padding: 24 }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
          ) : rows.length === 0 ? (
            <div style={{ padding: 24, display: "flex", alignItems: "center", gap: 8 }}>
              <CheckCircle2 size={18} style={{ color: "var(--workshop)" }} />
              {state === "decided" ? <span>Belum ada hari yang diputuskan di periode ini{kind ? " untuk jenis ini" : ""}.</span>
                                   : <span><b>Semua beres</b> untuk periode ini{kind ? " dan jenis ini" : ""}.</span>}
            </div>
          ) : (
            <>
              <table className="data-table">
                <thead><tr>
                  <th style={{ width: 36 }}><input type="checkbox" aria-label="Pilih semua di halaman ini" checked={allOnPage} onChange={togglePage} /></th>
                  <th>Tanggal</th><th>Karyawan</th><th>{state === "decided" ? "Keputusan" : "Status"}</th><th>Kenapa</th>
                  <th title="Usulan dari jam absen">Usulan absen</th><th title="Jam lembur yang dibayar, mis. 2 / 2,5 / 1:30">Lembur dibayar</th>
                </tr></thead>
                <tbody>
                  {rows.map((r) => {
                    const id = r.day_id!;
                    const isOpen = open && open.employee.id === r.employee.id && open.date === r.date;
                    const text = boxText(r);
                    const bad = hasBox(r) && parseHours(text) === null;
                    return (
                      <tr key={id} style={{ cursor: "pointer", background: isOpen ? "var(--paper)" : picked.has(id) || allMatching ? "var(--midnight-soft)" : undefined }}>
                        <td onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" aria-label={`Pilih ${r.employee.full_name} ${r.date}`} checked={allMatching || picked.has(id)} onChange={() => toggle(id)} />
                        </td>
                        <td className="mono" style={{ fontSize: 13, whiteSpace: "nowrap" }} onClick={() => setOpen(r)}>{dmy(r.date)}</td>
                        <td onClick={() => setOpen(r)}><div style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{r.employee.full_name}</div>
                          <div className="mono" style={{ fontSize: 12, color: "var(--steel)" }}>{r.employee.employee_no}</div></td>
                        <td onClick={() => setOpen(r)}>
                          {state === "decided"
                            ? <span className="pill" style={{ background: r.decision === "rejected" ? "var(--danger-lt, #fde8e8)" : "var(--workshop-lt)",
                                                              color: r.decision === "rejected" ? "var(--danger)" : "var(--workshop)" }}>
                                {r.decision === "rejected" ? "Ditolak" : (r.overtime_approved_minutes ? "Lembur dibayar" : "Hadir")}</span>
                            : <StatusPill status={r.status} label={r.status_label} />}
                        </td>
                        <td style={{ fontSize: 13, ...(open ? { maxWidth: 200, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } : {}) }}
                            title={r.review_reasons.join(" · ")} onClick={() => setOpen(r)}>
                          {r.hr_note && <div><HrNoteLine note={r.hr_note} maxWidth={open ? 200 : 360} /></div>}
                          {r.review_reasons.join(" · ")}</td>
                        <td style={{ fontSize: 13, whiteSpace: "nowrap", color: r.over_legal ? "var(--hazard-dark)" : undefined }}
                            title={r.over_legal ? "Lebih dari 4 jam di hari kerja (batas PP 35/2021): peringatan, tetap dibayar" : undefined}
                            onClick={() => setOpen(r)}>
                          {r.overtime_proposed_minutes ? minutesText(r.overtime_proposed_minutes) : "-"}
                        </td>
                        <td onClick={(e) => e.stopPropagation()} style={{ whiteSpace: "nowrap" }}>
                          {hasBox(r) ? (
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                              <input className="input" inputMode="decimal" value={text} aria-label={`Lembur dibayar ${r.employee.full_name} ${r.date}`}
                                     onChange={(e) => { setTyped({ ...typed, [id]: e.target.value }); if (!picked.has(id) && !allMatching) toggle(id); }}
                                     style={{ width: 64, padding: "4px 8px", fontSize: 13, ...(bad ? { borderColor: "var(--danger)" } : {}) }} />
                              <span style={{ fontSize: 12.5, color: "var(--steel)" }}>jam</span>
                            </span>
                          ) : <span style={{ color: "var(--steel)" }}>-</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {data && data.pages > 1 && (
                <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, padding: 10, borderTop: "1px solid var(--line)" }}>
                  <span style={{ fontSize: 13, color: "var(--steel)", marginRight: "auto" }}>{data.total} hari</span>
                  <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
                  <span style={{ fontSize: 13 }}>Hal. {data.page} / {data.pages}</span>
                  <button className="btn-ghost" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>›</button>
                </div>
              )}
            </>
          )}
        </div>
        {open && <DayPanel key={`${open.employee.id}-${open.date}`} row={open} onChanged={() => load()} onClose={() => setOpen(null)} />}
      </div>
    </div>
  );
}
