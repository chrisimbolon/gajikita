"use client";
// =============================================================================
// /dashboard/cuti/pengaturan — the company's leave rules (G14-1, 20 Nov 2026).
// Defaults follow UU No. 27 Tahun 2026; a company may choose otherwise, and the law shows next to each switch.
// The same rules appear on Payroll -> Aturan perusahaan vs UU.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { LeaveSettings, leaveSettingsApi } from "@/lib/api/leave";
import { ArrowLeft, CheckCircle2, Info, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

function Law({ ok, text }: { ok: boolean; text: string }) {
  return ok ? (
    <div style={{ fontSize: 12, color: "#2E7D4F", marginTop: 4 }}>
      <CheckCircle2 size={12} style={{ verticalAlign: "-1px" }} /> Sesuai {text}
    </div>
  ) : (
    <div style={{ fontSize: 12, color: "#2563A8", marginTop: 4 }}>
      <Info size={12} style={{ verticalAlign: "-1px" }} /> Berbeda dari {text}
    </div>
  );
}

export default function LeaveSettingsPage() {
  const [form, setForm] = useState<LeaveSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    leaveSettingsApi.get().then(setForm).catch((e) => setMessage({ ok: false, text: readErrors(e).summary }));
  }, []);

  const save = async () => {
    if (!form) return;
    setBusy(true); setMessage(null);
    try {
      setForm(await leaveSettingsApi.save(form));
      setMessage({ ok: true, text: "Pengaturan cuti disimpan." });
    } catch (e) {
      setMessage({ ok: false, text: readErrors(e).summary });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: 760 }}>
      <Link href="/dashboard/cuti" style={{ fontSize: 13.5, display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <ArrowLeft size={14} /> Cuti & Izin
      </Link>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
        <h1 className="display" style={{ fontSize: 28, textTransform: "none" }}>Pengaturan cuti</h1>
        <Link href="/dashboard/payroll/aturan-uu" style={{ fontSize: 13.5, fontWeight: 600 }}>Aturan perusahaan vs UU →</Link>
      </div>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        Bawaan SeeGaji mengikuti UU No. 27 Tahun 2026. Perusahaan boleh memilih lain; SeeGaji mencatat siapa yang mengubah.
      </p>

      {!form && !message && <div style={{ padding: 24 }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>}
      {form && (
        <>
          <div className="card" style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: "var(--midnight)" }}>Cuti bersama</div>
            <div style={{ fontSize: 13, color: "var(--steel)", margin: "2px 0 10px" }}>
              Hari cuti bersama dicatat di Absensi → Kejadian → Libur, dengan centang &quot;cuti bersama&quot;.
            </div>
            <label className="label" htmlFor="collective">Cuti bersama mengurangi cuti tahunan</label>
            <select id="collective" className="input" style={{ width: "100%" }}
                    value={form.collective_leave_reduces_annual ? "yes" : "no"}
                    onChange={(e) => setForm({ ...form, collective_leave_reduces_annual: e.target.value === "yes" })}>
              <option value="no">Tidak</option>
              <option value="yes">Ya, setiap hari cuti bersama memotong 1 hari cuti tahunan</option>
            </select>
            <Law ok={!form.collective_leave_reduces_annual}
                 text="UU No. 27/2026 Pasal 118 ayat 6 (cuti bersama tidak mengurangi cuti tahunan)" />
          </div>

          <div className="card" style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: "var(--midnight)" }}>Cuti pendampingan istri</div>
            <div style={{ fontSize: 13, color: "var(--steel)", margin: "2px 0 10px" }}>
              Istri melahirkan: 2 hari wajib, perusahaan boleh menambah paling lama 3 hari. Istri keguguran: 2 hari.
            </div>
            <label className="label" htmlFor="paternity">Tambahan cuti istri melahirkan</label>
            <select id="paternity" className="input" style={{ width: "100%" }} value={form.paternity_extra_days}
                    onChange={(e) => setForm({ ...form, paternity_extra_days: Number(e.target.value) })}>
              {[0, 1, 2, 3].map((n) => (
                <option key={n} value={n}>{n === 0 ? "Tidak ada (2 hari)" : `+${n} hari (total ${2 + n} hari)`}</option>
              ))}
            </select>
            <Law ok text="UU No. 27/2026 Pasal 124" />
          </div>

          <div className="card" style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: "var(--midnight)" }}>Cuti haid</div>
            <div style={{ fontSize: 13, color: "var(--steel)", margin: "2px 0 10px" }}>
              Untuk karyawan perempuan (isi Jenis kelamin di Karyawan). Paling lama 2 hari sebulan, tetap dibayar.
            </div>
            <label className="label" htmlFor="menstrual">Cuti haid bisa diajukan</label>
            <select id="menstrual" className="input" style={{ width: "100%" }} value={form.menstrual_leave ? "yes" : "no"}
                    onChange={(e) => setForm({ ...form, menstrual_leave: e.target.value === "yes" })}>
              <option value="yes">Ya</option>
              <option value="no">Tidak</option>
            </select>
            <Law ok={form.menstrual_leave} text="UU No. 27/2026 Pasal 120 dan 149 ayat 2 huruf b" />
          </div>

          {/* G14-2 */}
          <div className="card" style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: "var(--midnight)" }}>Cuti melahirkan dan istirahat keguguran</div>
            <div style={{ fontSize: 13, color: "var(--steel)", margin: "2px 0 10px" }}>
              Cuti melahirkan 3 bulan dibayar penuh, bisa diperpanjang sampai 3 bulan dengan surat dokter. Istirahat
              keguguran 1,5 bulan (atau sesuai surat dokter / bidan), dibayar penuh. Dicatat HR di Cuti &amp; Izin.
            </div>
            <label className="label" htmlFor="maternity">Upah bulan ke-5 dan ke-6 (perpanjangan)</label>
            <select id="maternity" className="input" style={{ width: "100%" }} value={form.maternity_extension_pay}
                    onChange={(e) => setForm({ ...form, maternity_extension_pay: Number(e.target.value) })}>
              {Array.from(new Set([75, 80, 90, 100, form.maternity_extension_pay])).sort((a, b) => a - b).map((n) => (
                <option key={n} value={n}>{n}% dari gaji pokok + tunjangan tetap{n === 75 ? " (UU)" : ""}</option>
              ))}
            </select>
            <Law ok={form.maternity_extension_pay >= 75}
                 text="UU No. 27/2026 Pasal 123 ayat 3 (bulan ke-4 penuh, bulan ke-5 dan ke-6 paling sedikit 75%)" />
          </div>

          <div className="card" style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: "var(--midnight)" }}>Istirahat panjang</div>
            <div style={{ fontSize: 13, color: "var(--steel)", margin: "2px 0 10px" }}>
              30 hari kalender, dibayar, setiap kali karyawan genap 5 tahun bekerja berturut-turut. Berlaku sampai
              5 tahun berikutnya. Di tahun istirahat panjang diambil, tidak ada cuti tahunan.
            </div>
            <label className="label" htmlFor="longrest">Istirahat panjang diberikan</label>
            <select id="longrest" className="input" style={{ width: "100%" }} value={form.long_rest ? "yes" : "no"}
                    onChange={(e) => setForm({ ...form, long_rest: e.target.value === "yes" })}>
              <option value="yes">Ya</option>
              <option value="no">Tidak</option>
            </select>
            <Law ok={form.long_rest} text="UU No. 27/2026 Pasal 118 ayat 2 huruf c dan ayat 4" />
          </div>

          <div className="card" style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: "var(--midnight)" }}>Tunjangan kehadiran saat cuti panjang</div>
            <div style={{ fontSize: 13, color: "var(--steel)", margin: "2px 0 10px" }}>
              Untuk periode yang ada cuti melahirkan, istirahat keguguran, atau istirahat panjang. Aturan perusahaan
              (tunjangan kehadiran bukan bagian upah tetap).
            </div>
            <label className="label" htmlFor="bonus">Tunjangan kehadiran</label>
            <select id="bonus" className="input" style={{ width: "100%" }}
                    value={form.long_leave_keeps_attendance_bonus ? "yes" : "no"}
                    onChange={(e) => setForm({ ...form, long_leave_keeps_attendance_bonus: e.target.value === "yes" })}>
              <option value="no">Tidak dibayar di periode itu</option>
              <option value="yes">Tetap dibayar</option>
            </select>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <button className="btn-rust" onClick={save} disabled={busy} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={15} />} Simpan
            </button>
          </div>
        </>
      )}
      {message && (
        <div style={{ marginTop: 12, fontSize: 14, color: message.ok ? "var(--workshop)" : "var(--danger)" }}>{message.text}</div>
      )}
    </div>
  );
}
