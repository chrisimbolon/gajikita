"use client";
// =============================================================================
// FingerprintImport — the "Import fingerprint" dialog on Absensi (G9, 1 Nov 2026).
// Choose the machine's file (attlog.dat, CSV, or the "Attendance Record Report" .xlsx/.xls),
// see what will be saved, then save. Saving the same file twice adds nothing; days already in a
// locked payroll are left alone.
// G12f.1b: with more than one machine, choose where the file comes from. Changing the choice
// clears the preview, so what is saved is always what was previewed.
// G12f.2: plain words first. One summary sentence in "hari kerja"; a red box when the file fits
// another machine better (one click to switch); a red row when the name in the machine does not
// look like the employee, and Simpan locked until HR ticks "Saya sudah cek"; unknown IDs come with
// "Ini siapa?" to link them right here.
// G12f.3.3: one job only, the machine's file. Notes from Excel are imported from Ringkasan → Persiapan awal.
// =============================================================================
import { Employee, hrApi, readErrors } from "@/lib/api/hr";
import { FingerprintImportResult, importApi } from "@/lib/api/imports";
import { AUTO_MACHINE, MAIN_MACHINE, MAIN_MACHINE_NAME, Machine, machineApi } from "@/lib/api/machines";
import { AlertTriangle, CheckCircle2, Fingerprint, Link2, Loader2, X } from "lucide-react";
import Link from "next/link";
import DeptBox from "@/components/DeptBox";                              // G12f.3.5
import { badNameText } from "@/components/DayNotesImport";
import { useEffect, useState } from "react";
import FingerprintDelete from "@/components/FingerprintDelete";

function d(iso: string) {
  const [y, m, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("id-ID", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" })
    .format(new Date(Date.UTC(y, m - 1, day)));
}

type Unknown = FingerprintImportResult["unknown"][number];
const unknownKey = (u: Unknown) => `${u.machine_key ?? "main"}|${u.machine_id}`;
const n = (x: number) => x.toLocaleString("id-ID");

export default function FingerprintImport({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<FingerprintImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [machines, setMachines] = useState<Machine[]>([]);       // G12f.1b: other machines (active)
  const [machine, setMachine] = useState<string>(MAIN_MACHINE);
  const [confirmNames, setConfirmNames] = useState(false);        // G12f.2: "Saya sudah cek"
  const [employees, setEmployees] = useState<Employee[]>([]);     // G12f.2: for "Ini siapa?"
  const [links, setLinks] = useState<Record<string, string>>({}); // unknown key -> employee id ("" = not linked)
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  useEffect(() => {
    machineApi.list().then((l) => setMachines(l.machines.filter((m) => m.is_active))).catch(() => setMachines([]));
  }, []);
  const several = machines.length > 0;

  const fresh = (r: FingerprintImportResult) => {
    setResult(r);
    setConfirmNames(false);
    setLinkError(null);
    setLinks(Object.fromEntries(r.unknown.map((u) => [unknownKey(u), u.suggest?.id ?? ""])));
    if (r.unknown.length > 0 && employees.length === 0) {
      hrApi.employees().then((list) => setEmployees(list.filter((e) => e.status === "active"))).catch(() => setEmployees([]));
    }
  };

  const run = async (commit: boolean, useMachine?: string) => {
    if (!file) return;
    const chosen = useMachine ?? machine;
    setBusy(true);
    setError(null);
    try {
      const r = await importApi.fingerprint(file, commit, several ? chosen : MAIN_MACHINE, commit && confirmNames);
      if (commit) { setResult(r); onDone(); } else fresh(r);
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  const switchMachine = (value: string) => { setMachine(value); setResult(null); run(false, value); };

  const linkAndRefresh = async () => {
    if (!result || result.suggest_machine) return;      // G12f.2b: never link under the wrong machine
    const chosen = result.unknown.filter((u) => links[unknownKey(u)]);
    if (chosen.length === 0) return;
    setLinking(true); setLinkError(null);
    try {
      await importApi.linkFingerprint(chosen.map((u) => ({
        machine: u.link_machine ?? MAIN_MACHINE, fingerprint_id: u.machine_id, employee: links[unknownKey(u)] })));
      await run(false);
    } catch (err) {
      setLinkError(readErrors(err).summary);
    } finally {
      setLinking(false);
    }
  };

  const [deleting, setDeleting] = useState(false);
  const t = result?.totals;
  const depts = result?.depts ?? [];
  const mismatches = t?.name_mismatch ?? 0;
  const locked = mismatches > 0 && !confirmNames;
  const suggestMachine = result && !result.applied ? result.suggest_machine : null;
  const chosenCount = result ? result.unknown.filter((u) => links[unknownKey(u)]).length : 0;
  const idLabel = (p: FingerprintImportResult["people"][number]) =>
    several && p.machines?.length ? p.machines.map((m) => `${m.machine_id} (${m.machine})`).join(", ") : p.machine_id;

  if (deleting) {
    return <FingerprintDelete period={result?.period} onBack={() => { setDeleting(false); setResult(null); setFile(null); }}
                              onClose={onClose} onDone={onDone} />;
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(1,61,90,0.45)", zIndex: 50, display: "flex", alignItems: "center",
                  justifyContent: "center", padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 860, maxWidth: "100%", maxHeight: "92vh", overflowY: "auto", padding: 22 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 19, fontWeight: 800, color: "var(--midnight)" }}>Import absensi dari mesin fingerprint</div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none" }}><X size={18} /></button>
        </div>
        <div style={{ fontSize: 13.5, color: "var(--steel)", margin: "4px 0 14px" }}>
          Pilih file dari mesin (<b>file Excel dari mesin</b> .xls / .xlsx, <b>attlog.dat</b> atau <b>CSV</b>)
          {several ? <>, lalu pilih <b>mesin asal file itu</b></> : null}. SeeGaji menunjukkan dulu apa yang akan disimpan.
          {" "}<button onClick={() => setDeleting(true)} style={{ background: "none", border: "none", padding: 0, color: "var(--rust)",
                                                                fontWeight: 600, cursor: "pointer", fontSize: 13.5 }}>
            Salah import? Hapus data import →
          </button>
        </div>

        {result?.applied ? (
          <div style={{ background: "var(--workshop-lt)", color: "var(--workshop)", borderRadius: 8, padding: "14px 16px", fontWeight: 700 }}>
            <CheckCircle2 size={16} style={{ verticalAlign: "-3px" }} /> Tersimpan: {n(result.applied.days)} hari kerja ({n(result.applied.events)} tap)
            {several && result.machine ? `, dari ${result.machine.name}` : ""}.
            <div style={{ fontWeight: 500, color: "var(--ink)", marginTop: 4, fontSize: 13.5 }}>
              Lembur, terlambat dan lupa absen pulang sekarang menunggu di <Link href="/dashboard/absensi/tinjau">Perlu Tinjau</Link>.
            </div>
            <div style={{ marginTop: 10 }}><button className="btn-rust" onClick={onClose}>Selesai</button></div>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <label className="btn-ghost" style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <Fingerprint size={15} /> {file ? file.name : "Pilih file dari mesin"}
              <input type="file" accept=".dat,.txt,.csv,.xlsx,.xls" style={{ display: "none" }}
                     onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null); }} />
            </label>
            {several && (
              <select className="input" aria-label="Mesin asal file" value={machine} style={{ width: "auto", minWidth: 220 }}
                      onChange={(e) => { setMachine(e.target.value); setResult(null); setError(null); }}>
                <option value={MAIN_MACHINE}>Dari {MAIN_MACHINE_NAME}</option>
                {machines.map((m) => <option key={m.id} value={m.id}>Dari {m.name}</option>)}
                <option value={AUTO_MACHINE}>Otomatis menurut Dept. di file</option>
              </select>
            )}
            <button className="btn-rust" disabled={!file || busy} onClick={() => run(false)}
                    style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />} Pratinjau
            </button>
          </div>
        )}

        {error && <div style={{ color: "var(--danger)", fontSize: 14, marginTop: 12 }}>{error}</div>}

        {result && t && !result.applied && (
          <div style={{ marginTop: 16 }}>
            {/* 1. Wrong machine: the most important thing, so it comes first */}
            {suggestMachine && (
              <div style={{ background: "var(--danger-light)", border: "1px solid var(--danger)", borderRadius: 8, padding: "12px 14px", marginBottom: 12 }}>
                <div style={{ fontWeight: 800, color: "var(--danger)", fontSize: 15 }}>
                  <AlertTriangle size={15} style={{ verticalAlign: "-2px" }} /> Sepertinya file ini dari {suggestMachine.name}, bukan {result.machine?.name ?? MAIN_MACHINE_NAME}.
                </div>
                <div style={{ fontSize: 13.5, margin: "4px 0 10px" }}>
                  Di {suggestMachine.name}, {suggestMachine.known} orang di file ini dikenali{suggestMachine.name_ok ? ` dan ${suggestMachine.name_ok} namanya cocok` : ""}.
                  Di {result.machine?.name ?? MAIN_MACHINE_NAME} hanya {suggestMachine.chosen_known} orang
                  {suggestMachine.chosen_name_bad ? `, dan ${suggestMachine.chosen_name_bad} namanya tidak cocok` : ""}.
                </div>
                <button className="btn-rust" disabled={busy} onClick={() => switchMachine(suggestMachine.value)}>
                  {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />} Ganti ke {suggestMachine.name} &amp; pratinjau lagi
                </button>
              </div>
            )}

            {/* 2. The plain summary */}
            <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "12px 14px", marginBottom: 12, fontSize: 14 }}>
              {result.file_period && (
                <div style={{ color: "var(--steel)", fontSize: 13 }}>
                  File ini berisi absensi {d(result.file_period.start)} – {d(result.file_period.end)} ({n(result.file_period.days)} hari)
                  {several && result.machine ? `, dibaca sebagai ${result.machine.name}` : ""}.
                  {" "}<span title={result.format}>{n(result.punches)} tap terbaca</span>
                  {result.unreadable > 0 && <span style={{ color: "var(--hazard-dark)" }}>, {n(result.unreadable)} tidak terbaca</span>}.
                </div>
              )}
              <div style={{ fontWeight: 800, fontSize: 16, color: "var(--midnight)", margin: "6px 0 2px" }}>
                {t.new_days > 0
                  ? `Siap disimpan: ${n(t.new_days)} hari kerja untuk ${n(t.people)} karyawan.`
                  : t.people > 0 ? "Tidak ada yang baru: semua hari kerja di file ini sudah ada di SeeGaji."
                                 : "Belum ada karyawan yang dikenali di file ini."}
              </div>
              {t.already_days > 0 && <div>{n(t.already_days)} hari kerja lain sudah ada di SeeGaji (diimport sebelumnya), jadi tidak disimpan dua kali.</div>}
              {t.locked_days > 0 && <div>{n(t.locked_days)} hari kerja sudah dibayar (payroll dikunci), jadi dilewati.</div>}
              <div style={{ color: "var(--steel)", fontSize: 12.5, marginTop: 4 }}>
                Satu hari kerja = satu karyawan pada satu tanggal, dijumlah untuk semua karyawan. Rinciannya per orang ada di tabel bawah.
              </div>
            </div>

            {/* 3. Names that do not match */}
            {mismatches > 0 && (
              <div style={{ background: "var(--danger-light)", borderRadius: 8, padding: "12px 14px", marginBottom: 12, fontSize: 13.5 }}>
                <div style={{ fontWeight: 800, color: "var(--danger)", fontSize: 14.5 }}>
                  <AlertTriangle size={14} style={{ verticalAlign: "-2px" }} /> {mismatches} karyawan: nama di mesin tidak cocok dengan nama di SeeGaji.
                </div>
                <div style={{ margin: "4px 0 8px" }}>
                  Lihat baris merah di tabel bawah. Biasanya artinya <b>salah pilih mesin</b> atau <b>salah nomor ID</b> di data karyawan.
                  Kalau disimpan juga, absensi orang di mesin akan masuk ke karyawan lain.
                </div>
                <label style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 600, cursor: "pointer" }}>
                  <input type="checkbox" checked={confirmNames} onChange={(e) => setConfirmNames(e.target.checked)} />
                  Saya sudah cek, nama-nama itu memang orang yang sama.
                </label>
              </div>
            )}

            {depts.length > 0 && several && result.machine?.mode === "auto" && (
              <DeptBox depts={depts} machines={machines} unit="tap"
                       onChanged={(all) => { setMachines(all.filter((m) => m.is_active)); run(false); }} />   /* G12f.3.5 */
            )}

            {/* 4. People in the file not yet linked: a to-do, not an error */}
            {result.unknown.length > 0 && (
              <div style={{ background: "var(--hazard-light)", borderRadius: 8, padding: "12px 14px", marginBottom: 12, fontSize: 13.5 }}>
                <div style={{ fontWeight: 800, color: "var(--hazard-dark)", fontSize: 14.5 }}>
                  {result.unknown.length} orang di file ini belum terhubung ke karyawan SeeGaji.
                </div>
                {suggestMachine ? (
                  <div style={{ margin: "4px 0 0" }}>
                    <b>Ganti mesin dulu</b> lewat tombol di kotak merah atas. Kalau orang dihubungkan sekarang, nomor mereka
                    tercatat di mesin yang salah.
                  </div>
                ) : (<>
                <div style={{ margin: "4px 0 10px" }}>
                  Absensi mereka belum ikut disimpan. Ini wajar saat pertama kali memakai mesin ini: pilih siapa orangnya
                  di kolom <b>Ini siapa?</b>, sekali saja. Bulan berikutnya otomatis. Yang sudah disarankan SeeGaji cukup dicek.
                </div>
                <div style={{ maxHeight: 260, overflowY: "auto", background: "var(--paper)", borderRadius: 6 }}>
                  <table className="data-table">
                    <thead><tr><th>Di mesin</th><th>Tap</th><th>Ini siapa?</th></tr></thead>
                    <tbody>
                      {result.unknown.map((u) => {
                        const key = unknownKey(u);
                        return (
                          <tr key={key}>
                            <td>
                              <div style={{ fontWeight: 600 }}>{u.name || "(tanpa nama)"}</div>
                              <div style={{ fontSize: 12, color: "var(--steel)" }}>ID {u.machine_id}{several && u.machine ? ` · ${u.machine}` : ""}</div>
                            </td>
                            <td>{n(u.taps)}</td>
                            <td>
                              <select className="input" aria-label={`Ini siapa: ${u.name || u.machine_id}`} value={links[key] ?? ""}
                                      onChange={(e) => setLinks((cur) => ({ ...cur, [key]: e.target.value }))} style={{ minWidth: 220 }}>
                                <option value="">— belum tahu / bukan karyawan —</option>
                                {employees.map((e) => (
                                  <option key={e.id} value={e.id}>
                                    {e.full_name} ({e.employee_no}){u.suggest?.id === e.id ? " · disarankan" : ""}
                                  </option>
                                ))}
                              </select>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {linkError && <div style={{ color: "var(--danger)", marginTop: 8 }}>{linkError}</div>}
                <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
                  <button className="btn-ghost" disabled={chosenCount === 0 || linking || busy} onClick={linkAndRefresh}
                          style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    {linking ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Link2 size={14} />}
                    {chosenCount === 0 ? "Pilih orangnya dulu" : `Hubungkan ${chosenCount} orang & pratinjau lagi`}
                  </button>
                </div>
                </>)}
              </div>
            )}

            {/* 5. Per person */}
            <div style={{ border: "1px solid var(--line)", borderRadius: 8, maxHeight: 320, overflowY: "auto" }}>
              <table className="data-table">
                <thead><tr><th>ID mesin</th><th>Karyawan</th><th>Hari kerja</th><th>Baru</th><th>Sudah ada</th><th>Tanpa pulang</th></tr></thead>
                <tbody>
                  {result.people.length === 0 && <tr><td colSpan={6} style={{ color: "var(--steel)" }}>Belum ada karyawan yang dikenali.</td></tr>}
                  {result.people.map((p) => {
                    const bad = p.name_check === "bad";
                    return (
                      <tr key={p.employee.id} style={bad ? { background: "var(--danger-light)" } : undefined}>
                        <td className="mono" style={{ fontSize: several ? 12.5 : undefined }}>{idLabel(p)}</td>
                        <td><div style={{ fontWeight: 600 }}>{p.employee.full_name}</div>
                          <div style={{ fontSize: 12, color: bad ? "var(--danger)" : "var(--steel)", fontWeight: bad ? 700 : 400 }}>
                            {bad ? badNameText(p.mismatch_name, p.names_in_file, "mesin")
                                 : `${p.employee.employee_no}${p.name_in_file ? ` · di mesin: ${p.name_in_file}` : ""}`}
                          </div></td>
                        <td>{p.days}</td><td>{p.new_days}</td><td>{p.already_days}</td>
                        <td style={{ color: p.no_clock_out ? "var(--hazard-dark)" : undefined }}>{p.no_clock_out}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {result.not_linked.length > 0 && (
              <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 8 }}>
                Karyawan aktif yang belum punya ID mesin: {result.not_linked.map((x) => x.full_name).join(", ")}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, marginTop: 14 }}>
              {locked && <span style={{ fontSize: 13, color: "var(--danger)", fontWeight: 600 }}>Cek dulu nama yang tidak cocok di atas.</span>}
              <button className="btn-ghost" onClick={onClose}>Batal</button>
              <button className="btn-rust" disabled={busy || t.new_days === 0 || locked} onClick={() => run(true)}>
                {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
                {t.new_days === 0 ? "Tidak ada hari kerja baru" : `Simpan ${n(t.new_days)} hari kerja (${n(t.people)} karyawan)`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
