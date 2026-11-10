"use client";
// =============================================================================
// SetupCard — "Persiapan awal" on Ringkasan (G12f.3.3, 10 Nov 2026). Lives on Ringkasan only, never in
// the sidebar. One card that walks a new company through setup in order and ticks each step by itself
// from what SeeGaji already holds:
//   1. Lokasi kerja   2. Shift   3. Karyawan                          (needed)
//   4. ID mesin fingerprint   5. Absensi bulan lalu   6. Catatan alasan dari Excel   (only if they apply)
// While a needed step is open the card is open at the top. Once 1-3 are done it folds into one line
// ("Persiapan awal selesai"), which still opens the optional steps: nothing is ever out of reach.
// Step 6 is the move-in path for reasons HR kept in Excel; plain words, no report or sheet names.
// =============================================================================
import DayNotesImport from "@/components/DayNotesImport";
import FingerprintImport from "@/components/FingerprintImport";
import { hrApi } from "@/lib/api/hr";
import { MachineList, machineApi } from "@/lib/api/machines";
import { CheckCircle2, ChevronDown, ChevronRight, Circle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const card = { background: "#FFFFFF", border: "1px solid #D5E0E8", borderRadius: 16 } as const;

interface Step {
  key: string; title: string; text: string; done: boolean | null;      // null = no tick (optional, can't tell)
  optional?: boolean; href?: string; action?: () => void; actionLabel: string;
}

export default function SetupCard({ sitesActive, employeesActive, onChanged }: {
  sitesActive: number; employeesActive: number; onChanged: () => void;
}) {
  const [shifts, setShifts] = useState<number | null>(null);
  const [machines, setMachines] = useState<MachineList | null>(null);
  const [open, setOpen] = useState<boolean | null>(null);                  // null = decide from the ticks
  const [modal, setModal] = useState<null | "taps" | "notes">(null);

  const load = useCallback(() => {
    hrApi.shifts().then((l) => setShifts(l.length)).catch(() => setShifts(0));
    machineApi.list().then(setMachines).catch(() => setMachines(null));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (shifts === null) return null;                                       // no flash of a half-ticked list

  const withIds = machines ? machines.main.employees + machines.machines.reduce((s, m) => s + m.employees, 0) : 0;
  const taps = machines ? machines.main.taps + machines.machines.reduce((s, m) => s + m.taps, 0) : 0;
  const steps: Step[] = [
    { key: "site", title: "Lokasi kerja", text: "Tempat karyawan bekerja: titik di peta dan radiusnya.",
      done: sitesActive > 0, href: "/dashboard/lokasi", actionLabel: "Buka Lokasi" },
    { key: "shift", title: "Shift", text: "Jam masuk, jam pulang dan toleransi terlambat.",
      done: shifts > 0, href: "/dashboard/shift", actionLabel: "Buka Shift" },
    { key: "people", title: "Data karyawan", text: "Tambah satu per satu, atau import dari file Excel karyawan yang sudah ada.",
      done: employeesActive > 0, href: "/dashboard/karyawan", actionLabel: "Buka Karyawan" },
    { key: "ids", title: "ID mesin fingerprint", optional: true,
      text: "Kalau absen pakai mesin sidik jari: isi nomor ID tiap karyawan di mesin (menu Karyawan), dan daftarkan mesin lain di Lokasi.",
      done: withIds > 0, href: "/dashboard/karyawan", actionLabel: "Isi ID di Karyawan" },
    { key: "taps", title: "Absensi bulan lalu", optional: true,
      text: "Import file dari mesin untuk periode sebelumnya, supaya payroll pertama punya data lengkap.",
      done: taps > 0, action: () => setModal("taps"), actionLabel: "Import file mesin" },
    { key: "notes", title: "Catatan alasan dari Excel", optional: true,
      text: "Kalau HR biasa menulis alasan per hari di Excel (mis. \"Mati lampu\", \"Cuti\"), SeeGaji bisa mengambilnya supaya " +
            "tampil di samping hari itu. File perlu kolom ID, Tanggal dan Keterangan. Tidak wajib.",
      done: null, action: () => setModal("notes"), actionLabel: "Ambil catatan" },
  ];
  const needed = steps.filter((s) => !s.optional);
  const neededDone = needed.filter((s) => s.done).length;
  const allNeeded = neededDone === needed.length;
  const isOpen = open ?? !allNeeded;
  const refresh = () => { load(); onChanged(); };

  return (
    <>
      {modal === "taps" && <FingerprintImport onClose={() => setModal(null)} onDone={refresh} />}
      {modal === "notes" && <DayNotesImport onClose={() => setModal(null)} onDone={refresh} onTaps={() => setModal("taps")} />}

      <div style={{ ...card, padding: isOpen ? "18px 22px" : "12px 18px" }}>
        <button onClick={() => setOpen(!isOpen)} style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", background: "none",
                                                          border: "none", padding: 0, cursor: "pointer", textAlign: "left" }}>
          {allNeeded ? <CheckCircle2 size={20} style={{ color: "var(--workshop)" }} />
                     : <span style={{ fontWeight: 800, color: "var(--midnight)", fontSize: 15 }}>{neededDone}/{needed.length}</span>}
          <span style={{ flexGrow: 1 }}>
            <span style={{ fontSize: allNeeded ? 14.5 : 18, fontWeight: 800, color: "var(--midnight)" }}>
              {allNeeded ? "Persiapan awal selesai" : "Persiapan awal"}
            </span>
            <span style={{ display: "block", fontSize: 13.5, color: "var(--steel)" }}>
              {allNeeded ? "Langkah tambahan (mesin fingerprint, data bulan lalu, catatan dari Excel) tetap bisa dibuka di sini."
                         : `${neededDone} dari ${needed.length} langkah wajib selesai. Ikuti dari atas ke bawah.`}
            </span>
          </span>
          {isOpen ? <ChevronDown size={18} style={{ color: "var(--steel)" }} /> : <ChevronRight size={18} style={{ color: "var(--steel)" }} />}
        </button>

        {isOpen && (
          <div style={{ marginTop: 10 }}>
            {steps.map((s, i) => (
              <div key={s.key} style={{ display: "flex", gap: 14, alignItems: "center", padding: "12px 0", borderTop: "1px solid #E6EDF2" }}>
                {s.done ? <CheckCircle2 size={20} style={{ color: "var(--workshop)", flexShrink: 0 }} />
                        : <Circle size={20} style={{ color: s.optional ? "var(--line)" : "var(--midnight)", flexShrink: 0 }} />}
                <div style={{ flexGrow: 1 }}>
                  <div style={{ fontWeight: 700 }}>
                    {i + 1}. {s.title}
                    {s.optional && <span style={{ fontWeight: 500, fontSize: 12.5, color: "var(--steel)" }}> · tidak wajib</span>}
                    {s.done && <span style={{ fontWeight: 600, fontSize: 12.5, color: "var(--workshop)" }}> · sudah</span>}
                  </div>
                  <div style={{ fontSize: 13.5, color: "var(--steel)" }}>{s.text}</div>
                </div>
                {s.href ? (
                  <Link href={s.href} className="btn-ghost" style={{ textDecoration: "none", whiteSpace: "nowrap", fontSize: 13.5 }}>{s.actionLabel}</Link>
                ) : (
                  <button className="btn-ghost" onClick={s.action} style={{ whiteSpace: "nowrap", fontSize: 13.5 }}>{s.actionLabel}</button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
