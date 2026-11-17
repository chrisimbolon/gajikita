"use client";
// =============================================================================
// OvertimeImport — "Ambil lembur dari file rekap" (G17-8, 17 Nov 2026). Opened from Siap gajian → Lembur.
// DKCB's HR writes the overtime he pays under each person's taps in his recap ("ASR Edit"): the taps checked
// against the paper SPL, rounded his way. Here SeeGaji reads that row and decides the days in one go:
//   1. choose the file (with several machines, where the IDs come from; default Otomatis)
//   2. preview per person: paid in the file / proposed by the taps / decided now, and what changes
//   3. Simpan keputusan lembur. Importing the same file again changes nothing. Urungkan puts every day back.
// =============================================================================
import { attendanceApi, minutesText } from "@/lib/api/attendance";
import { readErrors } from "@/lib/api/hr";
import { AUTO_MACHINE, MAIN_MACHINE, MAIN_MACHINE_NAME, Machine, machineApi } from "@/lib/api/machines";
import { OtLine, OtPerson, OvertimeImportResult, overtimeImportApi } from "@/lib/api/overtimeImport";
import { badNameText } from "@/components/DayNotesImport";
import DeptBox from "@/components/DeptBox";
import { AlertTriangle, CheckCircle2, FileSpreadsheet, Loader2, RotateCcw, X } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";

function d(iso: string) {
  const [y, m, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("id-ID", { timeZone: "UTC", weekday: "short", day: "numeric", month: "short" })
    .format(new Date(Date.UTC(y, m - 1, day)));
}
const n = (x: number) => x.toLocaleString("id-ID");
const h = (m: number | null) => (m ? minutesText(m) : "-");
const spin = { animation: "spin 1s linear infinite" };

const STATE: Record<OtLine["state"], { text: string; color: string }> = {
  pay: { text: "dibayar", color: "var(--workshop)" },
  unpay: { text: "jadi tanpa lembur", color: "var(--hazard-dark)" },
  none: { text: "tanpa lembur (tidak ada di file)", color: "var(--steel)" },
  same: { text: "sudah sama", color: "var(--steel)" },
  locked: { text: "payroll dikunci, dilewati", color: "var(--danger)" },
  rejected: { text: "ditolak HR, dilewati", color: "var(--danger)" },
  not_eligible: { text: "tidak berhak upah lembur, dilewati", color: "var(--danger)" },
  outside: { text: "di luar masa kerja, dilewati", color: "var(--danger)" },
};

function Shell({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(1,61,90,0.45)", zIndex: 50, display: "flex", alignItems: "center",
                  justifyContent: "center", padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 900, maxWidth: "100%", maxHeight: "92vh", overflowY: "auto", padding: 22 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 19, fontWeight: 800, color: "var(--midnight)" }}>Ambil lembur dari file rekap</div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none" }}><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Lines({ p }: { p: OtPerson }) {
  return (
    <table className="data-table" style={{ fontSize: 13 }}>
      <thead><tr><th>Tanggal</th><th>Jam absen</th><th>Usulan absen</th><th>Di file</th><th>Sekarang</th><th>Jadinya</th></tr></thead>
      <tbody>
        {p.lines.map((l) => (
          <tr key={l.date}>
            <td>{d(l.date)}</td>
            <td className="mono">{l.in || l.out ? `${l.in ?? "--"} – ${l.out ?? "--"}` : "tidak ada tap"}</td>
            <td>{h(l.proposed)}</td>
            <td style={{ fontWeight: 700 }}>{h(l.book)}</td>
            <td>{l.current === null ? "belum" : h(l.current)}</td>
            <td style={{ color: STATE[l.state].color, fontWeight: 600 }}>{STATE[l.state].text}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function OvertimeImport({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<OvertimeImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [machines, setMachines] = useState<Machine[]>([]);
  const [machine, setMachine] = useState<string>(MAIN_MACHINE);
  const [confirmNames, setConfirmNames] = useState(false);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [undone, setUndone] = useState<string | null>(null);

  useEffect(() => {
    machineApi.list().then((l) => {
      const active = l.machines.filter((m) => m.is_active);
      setMachines(active);
      if (active.length > 0) setMachine(AUTO_MACHINE);
    }).catch(() => setMachines([]));
  }, []);
  const several = machines.length > 0;

  const run = async (commit: boolean, useMachine?: string) => {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const r = await overtimeImportApi.run(file, commit, several ? (useMachine ?? machine) : MAIN_MACHINE, commit && confirmNames);
      setResult(r);
      if (commit) onDone(); else { setConfirmNames(false); setOpenRow(null); }
    } catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };
  const undo = async () => {
    const batch = result?.applied?.batch;
    if (!batch) return;
    setBusy(true); setError(null);
    try {
      const r = await attendanceApi.undoBulk(batch);
      setUndone(`Diurungkan: ${n(r.undone)} hari kembali seperti sebelum import${r.skipped ? ` (${n(r.skipped)} sudah diubah lagi, dibiarkan)` : ""}.`);
      onDone();
    } catch (err) { setError(readErrors(err).summary); }
    finally { setBusy(false); }
  };

  const t = result?.totals;
  const mismatches = t?.name_mismatch ?? 0;
  const blocked = mismatches > 0 && !confirmNames;
  const suggest = result && !result.applied ? result.suggest_machine : null;
  const skippedDays = t ? t.locked + t.rejected + t.not_eligible + t.outside : 0;
  const unknownOt = result ? result.unknown.filter((u) => u.minutes > 0) : [];

  return (
    <Shell onClose={onClose}>
      <div style={{ fontSize: 13.5, color: "var(--steel)", margin: "6px 0 14px" }}>
        Pilih file rekap absensi tempat HR menulis <b>jam lembur yang dibayar</b> di bawah jam absen tiap orang (seperti sheet
        {" "}&quot;ASR Edit&quot;). SeeGaji memutuskan lembur tiap hari sesuai file: ada jam = <b>dibayar</b> sebanyak itu,
        kosong = <b>hadir tanpa lembur</b>. Import file yang sama dua kali tidak mengubah apa-apa, dan bisa diurungkan.
      </div>

      {result?.applied ? (
        <div style={{ background: undone ? "var(--paper)" : "var(--workshop-lt)", borderRadius: 8, padding: "14px 16px" }}>
          {undone ? <div style={{ fontWeight: 700 }}>{undone}</div> : (
            <>
              <div style={{ fontWeight: 700, color: "var(--workshop)" }}>
                <CheckCircle2 size={16} style={{ verticalAlign: "-3px" }} /> Tersimpan: {n(result.applied.decided)} hari diputuskan,
                {" "}lembur dibayar {h(result.applied.minutes)}.
              </div>
              <div style={{ fontSize: 13.5, marginTop: 4 }}>
                Langkah Lembur di Siap gajian sekarang mengikuti file ini. Hitung ulang payroll periode ini supaya angkanya ikut berubah.
                {result.applied.skipped ? ` ${n(result.applied.skipped)} hari berubah sejak pratinjau, jadi dilewati.` : ""}
              </div>
            </>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="btn-rust" onClick={onClose}>Selesai</button>
            {!undone && result.applied.batch && (
              <button className="btn-ghost" disabled={busy} onClick={undo} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {busy ? <Loader2 size={14} style={spin} /> : <RotateCcw size={14} />} Urungkan
              </button>
            )}
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <label className="btn-ghost" style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <FileSpreadsheet size={15} /> {file ? file.name : "Pilih file Excel (.xlsx)"}
            <input type="file" accept=".xlsx,.xls" style={{ display: "none" }}
                   onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null); }} />
          </label>
          {several && (
            <select className="input" aria-label="Mesin asal ID di file" value={machine} style={{ width: "auto", minWidth: 220 }}
                    onChange={(e) => { setMachine(e.target.value); setResult(null); setError(null); }}>
              <option value={AUTO_MACHINE}>Otomatis menurut Department di file</option>
              <option value={MAIN_MACHINE}>Semua dari {MAIN_MACHINE_NAME}</option>
              {machines.map((m) => <option key={m.id} value={m.id}>Semua dari {m.name}</option>)}
            </select>
          )}
          <button className="btn-rust" disabled={!file || busy} onClick={() => run(false)} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {busy && <Loader2 size={15} style={spin} />} Pratinjau
          </button>
        </div>
      )}

      {error && <div style={{ color: "var(--danger)", fontSize: 14, marginTop: 12 }}>{error}</div>}

      {result && t && !result.applied && (
        <div style={{ marginTop: 16 }}>
          {suggest && (
            <div style={{ background: "var(--danger-light)", border: "1px solid var(--danger)", borderRadius: 8, padding: "12px 14px", marginBottom: 12 }}>
              <div style={{ fontWeight: 800, color: "var(--danger)" }}>
                <AlertTriangle size={15} style={{ verticalAlign: "-2px" }} /> Sepertinya ID di file ini cocok dengan {suggest.name}, bukan {result.machine.name}.
              </div>
              <button className="btn-rust" disabled={busy} style={{ marginTop: 8 }}
                      onClick={() => { setMachine(suggest.value); setResult(null); run(false, suggest.value); }}>
                Ganti ke {suggest.name} &amp; pratinjau lagi
              </button>
            </div>
          )}

          <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "12px 14px", marginBottom: 12, fontSize: 14 }}>
            <div style={{ color: "var(--steel)", fontSize: 13 }}>
              Sheet &quot;{result.sheet}&quot;, periode {d(result.period.start)} – {d(result.period.end)} · {n(t.people)} karyawan
              dikenali · total lembur di file <b>{h(t.file_minutes)}</b>.
            </div>
            <div style={{ fontWeight: 800, fontSize: 16, color: "var(--midnight)", margin: "6px 0 2px" }}>
              {t.todo ? `Siap diputuskan: ${n(t.todo)} hari untuk ${n(t.people_todo)} karyawan.` : "Tidak ada yang berubah: lembur di SeeGaji sudah sama dengan file ini."}
            </div>
            {t.todo > 0 && (
              <div>
                {t.pay > 0 && <>{n(t.pay)} hari lembur dibayar sesuai file. </>}
                {t.none > 0 && <>{n(t.none)} hari ada usulan dari jam absen tapi kosong di file: jadi hadir tanpa lembur. </>}
                {t.unpay > 0 && <>{n(t.unpay)} hari sudah dibayar lembur di SeeGaji tapi kosong di file: jadi tanpa lembur.</>}
              </div>
            )}
            {t.same > 0 && <div style={{ color: "var(--steel)" }}>{n(t.same)} hari sudah sama, tidak diubah.</div>}
            {skippedDays > 0 && (
              <div style={{ color: "var(--hazard-dark)", fontSize: 13, marginTop: 4 }}>
                Dilewati: {[t.locked && `${n(t.locked)} hari payroll dikunci`, t.rejected && `${n(t.rejected)} hari ditolak HR`,
                            t.not_eligible && `${n(t.not_eligible)} hari orang yang tidak berhak upah lembur`,
                            t.outside && `${n(t.outside)} hari di luar masa kerja`].filter(Boolean).join(", ")}.
              </div>
            )}
            {t.total_mismatch > 0 && (
              <div style={{ color: "var(--hazard-dark)", fontSize: 13, marginTop: 4 }}>
                {n(t.total_mismatch)} orang: jumlah per hari tidak sama dengan total yang ditulis di ujung baris. Cek baris kuning.
              </div>
            )}
            {result.no_row > 0 && (
              <div style={{ color: "var(--steel)", fontSize: 13, marginTop: 4 }}>
                {n(result.no_row)} orang di file tidak punya baris lembur, jadi lemburnya tidak diubah.
              </div>
            )}
          </div>

          {mismatches > 0 && (
            <div style={{ background: "var(--danger-light)", borderRadius: 8, padding: "12px 14px", marginBottom: 12, fontSize: 13.5 }}>
              <div style={{ fontWeight: 800, color: "var(--danger)" }}>
                <AlertTriangle size={14} style={{ verticalAlign: "-2px" }} /> {mismatches} karyawan: nama di file tidak cocok dengan nama di SeeGaji.
              </div>
              <div style={{ margin: "4px 0 8px" }}>Biasanya artinya salah pilih mesin atau salah nomor ID. Kalau disimpan juga, lemburnya masuk ke karyawan lain.</div>
              <label style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 600, cursor: "pointer" }}>
                <input type="checkbox" checked={confirmNames} onChange={(e) => setConfirmNames(e.target.checked)} />
                Saya sudah cek, nama-nama itu memang orang yang sama.
              </label>
            </div>
          )}

          {several && result.machine.mode === "auto" && (result.depts ?? []).length > 0 && (
            <DeptBox depts={result.depts ?? []} machines={machines}
                     onChanged={(all) => { setMachines(all.filter((m) => m.is_active)); run(false); }} />
          )}

          {unknownOt.length > 0 && (
            <div style={{ background: "var(--hazard-light)", borderRadius: 8, padding: "12px 14px", marginBottom: 12, fontSize: 13.5 }}>
              <b>{unknownOt.length} orang di file punya lembur tapi belum terhubung ke karyawan SeeGaji:</b>{" "}
              {unknownOt.map((u) => `${u.name || "(tanpa nama)"} · ID ${u.machine_id} · ${h(u.minutes)}`).join("  |  ")}.
              <div style={{ color: "var(--ink-soft)", marginTop: 2 }}>Lembur mereka tidak diambil. Hubungkan lewat Import file mesin → Ini siapa?, lalu ambil lagi.</div>
            </div>
          )}

          <div style={{ border: "1px solid var(--line)", borderRadius: 8, maxHeight: 380, overflowY: "auto" }}>
            <table className="data-table">
              <thead><tr><th>Karyawan</th><th>Lembur di file</th><th>Usulan absen</th><th>Berubah</th></tr></thead>
              <tbody>
                {result.people.filter((p) => p.lines.length || p.file_minutes).map((p) => {
                  const bad = p.name_check === "bad";
                  const isOpen = openRow === p.employee.id;
                  const warn = p.total_mismatch || p.unreadable.length > 0 || p.twice.length > 0;
                  return [
                    <tr key={p.employee.id} onClick={() => setOpenRow(isOpen ? null : p.employee.id)}
                        style={{ cursor: "pointer", background: bad ? "var(--danger-light)" : warn ? "var(--hazard-light)" : isOpen ? "var(--paper)" : undefined }}>
                      <td><div style={{ fontWeight: 600 }}>{isOpen ? "▾" : "▸"} {p.employee.full_name}</div>
                        <div style={{ fontSize: 12, color: bad ? "var(--danger)" : "var(--steel)", fontWeight: bad ? 700 : 400 }}>
                          {bad ? badNameText(p.mismatch_name, p.names_in_file, "file")
                               : `${p.employee.employee_no} · ID ${p.machine_id}${p.name_in_file ? ` · di file: ${p.name_in_file}` : ""}`}
                        </div>
                        {p.total_mismatch && <div style={{ fontSize: 12, color: "var(--hazard-dark)" }}>Total di ujung baris {h(p.file_total)}, jumlah per hari {h(p.file_minutes)}.</div>}
                        {p.unreadable.length > 0 && <div style={{ fontSize: 12, color: "var(--hazard-dark)" }}>Tidak terbaca: {p.unreadable.map((u) => `${d(u.date)} "${u.text}"`).join(", ")}.</div>}
                        {p.twice.length > 0 && <div style={{ fontSize: 12, color: "var(--hazard-dark)" }}>Ada di dua baris: {p.twice.map(d).join(", ")} (diambil yang lebih besar).</div>}
                      </td>
                      <td style={{ fontWeight: 700 }}>{h(p.file_minutes)}</td>
                      <td>{h(p.proposed_minutes)}</td>
                      <td>{p.todo ? <b>{n(p.todo)} hari</b> : <span style={{ color: "var(--steel)" }}>-</span>}</td>
                    </tr>,
                    isOpen && (
                      <tr key={`${p.employee.id}-lines`}>
                        <td colSpan={4} style={{ background: "var(--paper)", padding: "6px 12px 10px" }}>
                          {p.lines.length ? <Lines p={p} /> : <span style={{ color: "var(--steel)", fontSize: 13 }}>Tidak ada hari yang berubah.</span>}
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 6 }}>Klik nama untuk melihat per tanggal. Orang tanpa lembur dan tanpa usulan tidak ditampilkan.</div>

          <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, marginTop: 14 }}>
            {blocked && <span style={{ fontSize: 13, color: "var(--danger)", fontWeight: 600 }}>Cek dulu nama yang tidak cocok di atas.</span>}
            <button className="btn-ghost" onClick={onClose}>Batal</button>
            <button className="btn-rust" disabled={busy || !t.todo || blocked} onClick={() => run(true)}>
              {busy && <Loader2 size={15} style={spin} />} {t.todo ? `Simpan keputusan lembur (${n(t.todo)} hari)` : "Tidak ada yang berubah"}
            </button>
          </div>
        </div>
      )}
    </Shell>
  );
}
