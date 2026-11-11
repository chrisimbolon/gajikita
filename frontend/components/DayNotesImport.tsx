"use client";
// =============================================================================
// DayNotesImport — "Catatan alasan dari Excel" (G12f.3.2, 10 Nov 2026; G12f.3.3: opened from Ringkasan →
// Persiapan awal, no longer a tab of the machine import). Some HR teams keep a reason for each odd day in
// Excel, with a colour code: Mati lampu (blue = Lain), UL (yellow), Cuti (pink = CT) ...
// Here HR brings those notes in once, so they show beside each day in SeeGaji.
//   1. choose the recap file (and, with several machines, where the IDs come from; default Otomatis)
//   2. preview: what is new, changed, removed; names that don't match; IDs nobody has yet
//   3. Simpan. Importing the same file again changes nothing; locked (paid) days are left alone.
// A note never changes status, hours or pay: the screen says so.
// "Hapus catatan import" removes imported notes for a date range (with a reason, logged).
// =============================================================================
import { DayNotesDeleteResult, DayNotesImportResult, DayNotesPerson, dayNotesApi } from "@/lib/api/dayNotes";
import { readErrors } from "@/lib/api/hr";
import { AUTO_MACHINE, MAIN_MACHINE, MAIN_MACHINE_NAME, Machine, machineApi } from "@/lib/api/machines";
import { NoteCode } from "@/components/HrNote";
import { AlertTriangle, ArrowLeft, CheckCircle2, FileSpreadsheet, Loader2, Trash2, X } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";

function d(iso: string) {
  const [y, m, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("id-ID", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" })
    .format(new Date(Date.UTC(y, m - 1, day)));
}
const n = (x: number) => x.toLocaleString("id-ID");
const spin = { animation: "spin 1s linear infinite" };

/** G12f.3.4: the red line under a name. With two names under one ID, say both, so HR sees the second person. */
export function badNameText(mismatch: string | undefined, names: string[] | undefined, where: "mesin" | "file"): string {
  const all = names ?? [];
  const m = mismatch ?? "";
  return all.length > 1
    ? `Di ${where}, ID ini dipakai ${all.length} nama: ${all.map((x) => `"${x}"`).join(", ")}. "${m}" tidak mirip, cek dulu.`
    : `Nama di ${where}: "${m}". Tidak mirip, cek dulu.`;
}

const STATE_TEXT: Record<string, string> = { new: "baru", changed: "diubah", same: "sudah ada", locked: "terkunci" };

function Shell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(1,61,90,0.45)", zIndex: 50, display: "flex", alignItems: "center",
                  justifyContent: "center", padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 860, maxWidth: "100%", maxHeight: "92vh", overflowY: "auto", padding: 22 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 19, fontWeight: 800, color: "var(--midnight)" }}>{title}</div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none" }}><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export default function DayNotesImport({ onClose, onDone, onTaps }: { onClose: () => void; onDone: () => void; onTaps: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<DayNotesImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [machines, setMachines] = useState<Machine[]>([]);
  const [machine, setMachine] = useState<string>(MAIN_MACHINE);
  const [confirmNames, setConfirmNames] = useState(false);
  const [openRows, setOpenRows] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    machineApi.list().then((l) => {
      const active = l.machines.filter((m) => m.is_active);
      setMachines(active);
      if (active.length > 0) setMachine(AUTO_MACHINE);        // a recap usually holds every machine, by Department
    }).catch(() => setMachines([]));
  }, []);
  const several = machines.length > 0;

  const run = async (commit: boolean, useMachine?: string) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await dayNotesApi.importNotes(file, commit, several ? (useMachine ?? machine) : MAIN_MACHINE, commit && confirmNames);
      setResult(r);
      if (commit) onDone(); else { setConfirmNames(false); setOpenRows(new Set()); }
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };
  const switchMachine = (value: string) => { setMachine(value); setResult(null); run(false, value); };
  const toggleRow = (id: string) => setOpenRows((cur) => { const s = new Set(cur); if (s.has(id)) s.delete(id); else s.add(id); return s; });

  if (deleting) {
    return <NotesDelete period={result?.period} onBack={() => { setDeleting(false); setResult(null); setFile(null); }}
                        onClose={onClose} onDone={onDone} />;
  }

  const t = result?.totals;
  const changes = t ? t.new + t.changed + t.removed : 0;
  const toSave = t ? t.new + t.changed : 0;
  const peopleToSave = result ? result.people.filter((p) => p.new + p.changed > 0).length : 0;
  const mismatches = t?.name_mismatch ?? 0;
  const locked = mismatches > 0 && !confirmNames;
  const suggest = result && !result.applied ? result.suggest_machine : null;
  const idLabel = (p: DayNotesPerson) =>
    several && p.machines.length ? p.machines.map((m) => `${m.machine_id} (${m.machine})`).join(", ") : p.machine_id;
  const saveLabel = !t ? "" : changes === 0 ? "Tidak ada yang berubah"
    : t.changed === 0 && t.removed === 0 ? `Simpan ${n(t.new)} catatan (${n(peopleToSave)} karyawan)`
    : `Simpan perubahan: ${[t.new && `${n(t.new)} baru`, t.changed && `${n(t.changed)} diubah`, t.removed && `${n(t.removed)} dihapus`]
        .filter(Boolean).join(", ")}`;

  return (
    <Shell title="Ambil catatan alasan dari Excel" onClose={onClose}>
      <div style={{ fontSize: 13.5, color: "var(--steel)", margin: "6px 0 14px" }}>
        Pilih file Excel tempat HR menulis alasan per hari. File perlu kolom <b>ID</b> (nomor di mesin), <b>Tanggal</b> dan
        {" "}<b>Keterangan</b>; SeeGaji mencari sendiri sheet dan kolomnya.
        SeeGaji membaca <b>catatan dan warnanya</b> saja, lalu menampilkannya di samping hari itu.
        Jam absen, status dan gaji <b>tidak berubah</b> karena catatan.
        {" "}<button onClick={() => setDeleting(true)} style={{ background: "none", border: "none", padding: 0, color: "var(--rust)",
                                                                fontWeight: 600, cursor: "pointer", fontSize: 13.5 }}>
          Salah import? Hapus catatan import →
        </button>
      </div>

      {result?.applied ? (
        <div style={{ background: "var(--workshop-lt)", color: "var(--workshop)", borderRadius: 8, padding: "14px 16px", fontWeight: 700 }}>
          <CheckCircle2 size={16} style={{ verticalAlign: "-3px" }} /> Tersimpan:{" "}
          {[`${n(result.applied.added)} catatan baru`, result.applied.changed ? `${n(result.applied.changed)} diubah` : "",
            result.applied.removed ? `${n(result.applied.removed)} dihapus` : ""].filter(Boolean).join(", ")}.
          <div style={{ fontWeight: 500, color: "var(--ink)", marginTop: 4, fontSize: 13.5 }}>
            Catatannya sekarang tampil di Absensi harian, di panel hari, di Rekap (sudut sel berwarna) dan di Perlu Tinjau
            (saringan &quot;Ada catatan HR&quot;).
          </div>
          <div style={{ marginTop: 10 }}><button className="btn-rust" onClick={onClose}>Selesai</button></div>
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
          <button className="btn-rust" disabled={!file || busy} onClick={() => run(false)}
                  style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {busy && <Loader2 size={15} style={spin} />} Pratinjau
          </button>
        </div>
      )}

      {error && <div style={{ color: "var(--danger)", fontSize: 14, marginTop: 12 }}>{error}</div>}

      {result && t && !result.applied && (
        <div style={{ marginTop: 16 }}>
          {/* 1. Wrong machine first */}
          {suggest && (
            <div style={{ background: "var(--danger-light)", border: "1px solid var(--danger)", borderRadius: 8, padding: "12px 14px", marginBottom: 12 }}>
              <div style={{ fontWeight: 800, color: "var(--danger)", fontSize: 15 }}>
                <AlertTriangle size={15} style={{ verticalAlign: "-2px" }} /> Sepertinya ID di file ini cocok dengan {suggest.name}, bukan {result.machine.name}.
              </div>
              <div style={{ fontSize: 13.5, margin: "4px 0 10px" }}>
                Dengan {suggest.name}, {suggest.known} orang dikenali{suggest.name_ok ? ` dan ${suggest.name_ok} namanya cocok` : ""}.
                Dengan {result.machine.name} hanya {suggest.chosen_known} orang
                {suggest.chosen_name_bad ? `, dan ${suggest.chosen_name_bad} namanya tidak cocok` : ""}.
              </div>
              <button className="btn-rust" disabled={busy} onClick={() => switchMachine(suggest.value)}>
                {busy && <Loader2 size={15} style={spin} />} Ganti ke {suggest.name} &amp; pratinjau lagi
              </button>
            </div>
          )}

          {/* 2. The plain summary */}
          <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "12px 14px", marginBottom: 12, fontSize: 14 }}>
            <div style={{ color: "var(--steel)", fontSize: 13 }}>
              Sheet &quot;{result.sheet}&quot;, catatan {d(result.period.start)} – {d(result.period.end)}
              {result.period_in_file ? "" : " (tanggal pertama sampai terakhir di file)"}
              {several ? `, ID dibaca ${result.machine.mode === "auto" ? "otomatis menurut Department" : `sebagai ${result.machine.name}`}` : ""}.
            </div>
            <div style={{ fontWeight: 800, fontSize: 16, color: "var(--midnight)", margin: "6px 0 2px" }}>
              {toSave > 0 ? `Siap disimpan: ${n(toSave)} catatan untuk ${n(peopleToSave)} karyawan.`
                : t.removed > 0 ? `Siap disimpan: ${n(t.removed)} catatan lama dihapus.`
                : t.people > 0 ? "Tidak ada yang berubah: semua catatan di file ini sudah ada di SeeGaji."
                               : "Belum ada karyawan yang dikenali di file ini."}
            </div>
            {(t.changed > 0 || t.removed > 0) && (
              <div>
                {t.new > 0 && <>{n(t.new)} baru. </>}
                {t.changed > 0 && <>{n(t.changed)} catatan berubah sejak import sebelumnya (lihat &quot;diubah&quot; di tabel). </>}
                {t.removed > 0 && <>{n(t.removed)} catatan lama tidak ada lagi di file ini, jadi dihapus.</>}
              </div>
            )}
            {t.same > 0 && <div>{n(t.same)} catatan sudah ada di SeeGaji, tidak disimpan dua kali.</div>}
            {t.locked > 0 && <div>{n(t.locked)} catatan jatuh di hari yang sudah dibayar (payroll dikunci), jadi dilewati.</div>}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginTop: 8, fontSize: 13 }}>
              {result.legend.length > 0 ? (
                <><span style={{ color: "var(--steel)" }}>Kode warna di file:</span>
                  {result.legend.map((l) => <NoteCode key={l.color} code={l.label} color={l.color} />)}</>
              ) : (
                <span style={{ color: "var(--steel)" }}>
                  {result.colors_read ? "File ini tidak punya legenda warna, jadi catatan disimpan dengan warnanya saja (tanpa kode)."
                                      : "Warna tidak terbaca dari file .xls lama. Buka di Excel lalu Save As .xlsx supaya kode UL / CT ikut."}
                </span>
              )}
            </div>
            {(result.unreadable > 0 || result.outside > 0) && (
              <div style={{ color: "var(--hazard-dark)", fontSize: 13, marginTop: 6 }}>
                {result.unreadable > 0 && <>{n(result.unreadable)} baris tanggalnya tidak terbaca. </>}
                {result.outside > 0 && <>{n(result.outside)} baris di luar periode laporan, tidak diambil.</>}
              </div>
            )}
          </div>

          {/* 3. Names that do not match */}
          {mismatches > 0 && (
            <div style={{ background: "var(--danger-light)", borderRadius: 8, padding: "12px 14px", marginBottom: 12, fontSize: 13.5 }}>
              <div style={{ fontWeight: 800, color: "var(--danger)", fontSize: 14.5 }}>
                <AlertTriangle size={14} style={{ verticalAlign: "-2px" }} /> {mismatches} karyawan: nama di file tidak cocok dengan nama di SeeGaji.
              </div>
              <div style={{ margin: "4px 0 8px" }}>
                Lihat baris merah di tabel bawah. Biasanya artinya <b>salah pilih mesin</b> atau <b>salah nomor ID</b> di data karyawan.
                Kalau disimpan juga, catatan orang itu tampil di karyawan lain.
              </div>
              <label style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 600, cursor: "pointer" }}>
                <input type="checkbox" checked={confirmNames} onChange={(e) => setConfirmNames(e.target.checked)} />
                Saya sudah cek, nama-nama itu memang orang yang sama.
              </label>
            </div>
          )}

          {/* 4. A date written twice */}
          {result.repeated.length > 0 && (
            <div style={{ background: "var(--hazard-light)", borderRadius: 8, padding: "10px 14px", marginBottom: 12, fontSize: 13.5 }}>
              <b>Tanggal yang ditulis dua kali di file:</b>{" "}
              {result.repeated.map((r) => `${r.name || "ID " + r.machine_id} (ID ${r.machine_id}) ${d(r.date)}`).join(" · ")}.
              <div style={{ color: "var(--ink-soft)", marginTop: 2 }}>
                Catatannya digabung jadi satu. Kalau salah satu sebenarnya tanggal lain, perbaiki di file rekap lalu import lagi.
              </div>
            </div>
          )}

          {/* 4b. G12f.3.4: which machine each Department was read as */}
          {several && result.machine.mode === "auto" && (result.depts ?? []).length > 0 && (
            <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "8px 12px", marginBottom: 12, fontSize: 13.5 }}>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>Department di file → mesin</div>
              {(result.depts ?? []).map((x) => (
                <div key={x.dept}>{x.dept} → <b>{x.machine}</b> · {x.people} orang
                  {!x.claimed && <span style={{ color: "var(--steel)" }}> (Department ini tidak terdaftar di mesin lain)</span>}</div>
              ))}
              <div style={{ color: "var(--steel)", fontSize: 12.5, marginTop: 4 }}>
                Ada yang seharusnya mesin lain? Isi Department-nya di Lokasi → Mesin fingerprint (pisahkan dengan koma,
                mis. &quot;Staf, Manager&quot;), lalu pratinjau lagi.
              </div>
            </div>
          )}

          {/* 5. IDs nobody has yet */}
          {result.unknown.length > 0 && (
            <div style={{ background: "var(--hazard-light)", borderRadius: 8, padding: "12px 14px", marginBottom: 12, fontSize: 13.5 }}>
              <div style={{ fontWeight: 800, color: "var(--hazard-dark)", fontSize: 14.5 }}>
                {result.unknown.length} orang di file ini belum terhubung ke karyawan SeeGaji
                {t.unknown_notes ? ` (${n(t.unknown_notes)} catatan belum ikut)` : ""}.
              </div>
              <div style={{ margin: "4px 0 6px" }}>
                Hubungkan dulu lewat <button onClick={onTaps} style={{ background: "none", border: "none", padding: 0, color: "var(--rust)",
                fontWeight: 700, cursor: "pointer", fontSize: 13.5 }}>Import file mesin</button> → kolom <b>Ini siapa?</b>, lalu ambil catatan ini lagi.
                Yang memang bukan karyawan (mis. sudah keluar) boleh dibiarkan.
              </div>
              <div style={{ color: "var(--ink-soft)" }}>
                {result.unknown.map((u) => `${u.name || "(tanpa nama)"} · ID ${u.machine_id}${several ? ` · ${u.machine}` : ""}`).join("  |  ")}
              </div>
            </div>
          )}

          {/* 6. Per person */}
          <div style={{ border: "1px solid var(--line)", borderRadius: 8, maxHeight: 360, overflowY: "auto" }}>
            <table className="data-table">
              <thead><tr><th>ID</th><th>Karyawan</th><th>Kode</th><th>Catatan</th><th>Baru</th><th>Diubah</th><th>Dihapus</th></tr></thead>
              <tbody>
                {result.people.length === 0 && <tr><td colSpan={7} style={{ color: "var(--steel)" }}>Belum ada karyawan yang dikenali.</td></tr>}
                {result.people.map((p) => {
                  const bad = p.name_check === "bad";
                  const isOpen = openRows.has(p.employee.id);
                  return [
                    <tr key={p.employee.id} onClick={() => toggleRow(p.employee.id)}
                        style={{ cursor: "pointer", background: bad ? "var(--danger-light)" : isOpen ? "var(--paper)" : undefined }}>
                      <td className="mono" style={{ fontSize: several ? 12.5 : undefined }}>{idLabel(p)}</td>
                      <td><div style={{ fontWeight: 600 }}>{isOpen ? "▾" : "▸"} {p.employee.full_name}</div>
                        <div style={{ fontSize: 12, color: bad ? "var(--danger)" : "var(--steel)", fontWeight: bad ? 700 : 400 }}>
                          {bad ? badNameText(p.mismatch_name, p.names_in_file, "file")
                               : `${p.employee.employee_no}${p.name_in_file ? ` · di file: ${p.name_in_file}` : ""}`}
                        </div></td>
                      <td><div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {p.codes.map((c) => {
                          const color = result.legend.find((l) => l.label === c.code)?.color ?? "";
                          return <NoteCode key={c.code} code={c.code} color={color} count={c.count} />;
                        })}
                      </div></td>
                      <td>{p.notes}</td>
                      <td>{p.new || "-"}</td>
                      <td style={{ color: p.changed ? "var(--hazard-dark)" : undefined }}>{p.changed || "-"}</td>
                      <td style={{ color: p.removed ? "var(--danger)" : undefined }}>{p.removed || "-"}</td>
                    </tr>,
                    isOpen && (
                      <tr key={`${p.employee.id}-lines`}>
                        <td colSpan={7} style={{ background: "var(--paper)", padding: "6px 12px 10px" }}>
                          {p.lines.length === 0 ? (
                            <span style={{ color: "var(--steel)", fontSize: 13 }}>Tidak ada catatan untuk orang ini di file (catatan lamanya dihapus).</span>
                          ) : p.lines.map((l) => (
                            <div key={l.date} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 13, padding: "2px 0" }}>
                              <span className="mono" style={{ minWidth: 92, color: "var(--steel)" }}>{d(l.date)}</span>
                              <NoteCode code={l.code} color={l.color} />
                              <span style={{ flex: 1 }}>{l.text}
                                {l.state === "changed" && l.before && <span style={{ color: "var(--steel)" }}> (sebelumnya: {l.before})</span>}
                              </span>
                              <span style={{ fontSize: 12, fontWeight: 700, color: l.state === "new" ? "var(--workshop)"
                                             : l.state === "changed" ? "var(--hazard-dark)" : "var(--steel)" }}>{STATE_TEXT[l.state]}</span>
                            </div>
                          ))}
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 6 }}>Klik nama untuk melihat catatannya per tanggal.</div>

          <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, marginTop: 14 }}>
            {locked && <span style={{ fontSize: 13, color: "var(--danger)", fontWeight: 600 }}>Cek dulu nama yang tidak cocok di atas.</span>}
            <button className="btn-ghost" onClick={onClose}>Batal</button>
            <button className="btn-rust" disabled={busy || changes === 0 || locked} onClick={() => run(true)}>
              {busy && <Loader2 size={15} style={spin} />} {saveLabel}
            </button>
          </div>
        </div>
      )}
    </Shell>
  );
}

// ── "Hapus catatan import" ──
function NotesDelete({ period, onBack, onClose, onDone }: {
  period?: { start: string; end: string }; onBack: () => void; onClose: () => void; onDone: () => void;
}) {
  const [start, setStart] = useState(period?.start ?? "");
  const [end, setEnd] = useState(period?.end ?? "");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<DayNotesDeleteResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (commit: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await dayNotesApi.deleteNotes({ start, end, commit, reason });
      setResult(r);
      if (commit) onDone();
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };
  const changed = () => { setResult(null); setError(null); };
  const t = result?.totals;

  return (
    <Shell title="Hapus catatan HR hasil import" onClose={onClose}>
      <button onClick={onBack} style={{ background: "none", border: "none", color: "var(--rust)", fontWeight: 600, fontSize: 13.5,
                                        padding: 0, margin: "2px 0 8px", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
        <ArrowLeft size={14} /> Kembali ke import catatan
      </button>
      <div style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 14 }}>
        Untuk file yang salah: hapus catatan hasil import di tanggal ini, lalu ambil lagi dari file yang benar. Hanya <b>catatan</b> yang
        dihapus; jam absen, keputusan HR dan gaji tidak disentuh. Hari yang sudah masuk payroll terkunci tetap.
      </div>

      {result?.applied ? (
        <div style={{ background: "var(--workshop-lt)", color: "var(--workshop)", borderRadius: 8, padding: "14px 16px", fontWeight: 700 }}>
          <CheckCircle2 size={16} style={{ verticalAlign: "-3px" }} /> Terhapus: {n(result.applied.removed)} catatan.
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <button className="btn-ghost" onClick={onBack}>Import file yang benar</button>
            <button className="btn-rust" onClick={onClose}>Selesai</button>
          </div>
        </div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div><label className="label">Dari tanggal</label>
              <input className="input" type="date" value={start} onChange={(e) => { setStart(e.target.value); changed(); }} /></div>
            <div><label className="label">Sampai tanggal</label>
              <input className="input" type="date" value={end} onChange={(e) => { setEnd(e.target.value); changed(); }} /></div>
            <button className="btn-ghost" disabled={!start || !end || busy} onClick={() => run(false)}
                    style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {busy && !result && <Loader2 size={15} style={spin} />} Lihat dulu
            </button>
          </div>

          {result && t && (
            <div style={{ marginTop: 14 }}>
              <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "12px 14px", fontSize: 14 }}>
                <div style={{ fontWeight: 800, fontSize: 16, color: "var(--midnight)" }}>
                  {t.notes > 0 ? `Akan dihapus: ${n(t.notes)} catatan dari ${n(t.people)} karyawan.`
                               : "Tidak ada catatan import di tanggal ini."}
                </div>
                {t.locked > 0 && <div>{n(t.locked)} catatan di hari yang sudah dibayar (payroll dikunci) tetap disimpan.</div>}
                {result.people.length > 0 && (
                  <div style={{ color: "var(--steel)", fontSize: 13, marginTop: 4 }}>
                    {result.people.map((p) => `${p.employee.full_name} (${p.notes})`).join(", ")}
                  </div>
                )}
              </div>
              {t.notes > 0 && (
                <div style={{ marginTop: 12 }}>
                  <label className="label">Alasan (wajib, tercatat di log)</label>
                  <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="mis. salah file, import ulang" />
                  <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
                    <button className="btn-ghost" onClick={onClose}>Batal</button>
                    <button className="btn-rust" disabled={busy || reason.trim().length < 5} onClick={() => run(true)}
                            style={{ display: "flex", alignItems: "center", gap: 6, background: "var(--danger)" }}>
                      {busy ? <Loader2 size={15} style={spin} /> : <Trash2 size={15} />} Hapus {n(t.notes)} catatan
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
      {error && <div style={{ color: "var(--danger)", fontSize: 14, marginTop: 12 }}>{error}</div>}
    </Shell>
  );
}
