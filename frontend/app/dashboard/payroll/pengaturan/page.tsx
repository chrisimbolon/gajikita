"use client";
// =============================================================================
// /dashboard/payroll/pengaturan — the company's payroll settings (G8b part 1, 1 Nov 2026).
// Defaults follow the law (PP 35/2021 overtime); a company can choose its own flat
// rates, and GajiKita then shows a warning on every slip where that pays less.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { DKCB_NIGHT_RULES, NightRule, PayrollSettings, payrollApi } from "@/lib/api/payroll";
import { ArrowLeft, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

// G11c: money reads "12.500" while typing; saved as plain digits
const RP = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });
function moneyText(value: string): string {
  if (value === "" || value == null) return "";
  const n = Math.trunc(Number(value));
  return Number.isFinite(n) ? RP.format(n) : value;
}

const JKK = [["0.0024", "Kelompok 1 · 0,24% (risiko sangat rendah)"], ["0.0054", "Kelompok 2 · 0,54%"],
             ["0.0089", "Kelompok 3 · 0,89%"], ["0.0127", "Kelompok 4 · 1,27%"], ["0.0174", "Kelompok 5 · 1,74% (risiko sangat tinggi)"]];

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 16, fontWeight: 800, color: "var(--midnight)" }}>{title}</div>
      {hint && <div style={{ fontSize: 13, color: "var(--steel)", margin: "2px 0 10px" }}>{hint}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, marginTop: hint ? 0 : 10 }}>
        {children}
      </div>
    </div>
  );
}

export default function PayrollSettingsPage() {
  const [form, setForm] = useState<PayrollSettings | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    payrollApi.settings().then(setForm).catch((err) => setMessage({ ok: false, text: readErrors(err).summary }));
  }, []);

  if (!form) {
    return <div style={{ padding: 24, color: "var(--steel)" }}>{message?.text ?? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />}</div>;
  }

  const set = <K extends keyof PayrollSettings>(k: K, v: PayrollSettings[K]) => setForm({ ...form, [k]: v });
  const err = (k: string) => errors[k] && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 4 }}>{errors[k]}</div>;
  const money = (k: keyof PayrollSettings, label: string, hint?: string) => (
    <label>
      <div className="label">{label}</div>
      <div style={{ position: "relative" }}>
        <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--steel)",
                       fontSize: 14, pointerEvents: "none" }}>Rp</span>
        <input className="input" inputMode="numeric" value={moneyText(String(form[k] ?? ""))} style={{ width: "100%", paddingLeft: 40 }}
               onChange={(e) => set(k, e.target.value.replace(/\D/g, "").slice(0, 13) as never)} />
      </div>
      {hint && <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 3 }}>{hint}</div>}
      {err(k)}
    </label>
  );
  const number = (k: keyof PayrollSettings, label: string, hint?: string) => (
    <label>
      <div className="label">{label}</div>
      <input className="input" type="number" min={0} value={Number(form[k] ?? 0)} style={{ width: "100%" }}
             onChange={(e) => set(k, Number(e.target.value) as never)} />
      {hint && <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 3 }}>{hint}</div>}
      {err(k)}
    </label>
  );

  // G12e: the night-overtime rows
  const nightRules: NightRule[] = form.night_ot_rules ?? [];
  const setRules = (next: NightRule[]) => set("night_ot_rules", next);
  const setRule = (i: number, patch: Partial<NightRule>) => setRules(nightRules.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const save = async () => {
    setBusy(true);
    setErrors({});
    setMessage(null);
    try {
      setForm(await payrollApi.saveSettings(form));
      setMessage({ ok: true, text: "Pengaturan payroll disimpan." });
    } catch (e) {
      const r = readErrors(e);
      setErrors(r.fields);
      setMessage({ ok: false, text: r.summary });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: 900 }}>
      <Link href="/dashboard/payroll" style={{ fontSize: 13.5, display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <ArrowLeft size={14} /> Payroll
      </Link>
      <h1 className="display" style={{ fontSize: 28, marginBottom: 14, textTransform: "none" }}>Pengaturan payroll</h1>

      <Section title="Periode" hint="Misalnya periode 26 s/d 25 dan gajian tanggal 5 bulan berikutnya.">
        {number("period_start_day", "Periode mulai tanggal", "1 = per bulan kalender")}
        {number("pay_day", "Tanggal gajian")}
        <label>
          <div className="label">Pembagi gaji harian</div>
          <select className="input" value={form.daily_divisor} onChange={(e) => set("daily_divisor", Number(e.target.value))} style={{ width: "100%" }}>
            {[30, 31, 26, 25, 21].map((n) => <option key={n} value={n}>Gaji pokok ÷ {n}</option>)}
          </select>
          <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 3 }}>Untuk potongan tidak hadir dan unpaid leave</div>
          {err("daily_divisor")}
        </label>
      </Section>

      <Section title="Lembur" hint="PP 35/2021 adalah aturan yang berlaku. Jika memakai tarif tetap, setiap slip yang lebih rendah dari PP 35 diberi peringatan.">
        <label>
          <div className="label">Cara hitung</div>
          <select className="input" value={form.overtime_mode} onChange={(e) => set("overtime_mode", e.target.value as PayrollSettings["overtime_mode"])} style={{ width: "100%" }}>
            <option value="pp35">Sesuai PP 35/2021 (1/173 × upah, 1,5× / 2×)</option>
            <option value="flat">Tarif tetap perusahaan</option>
          </select>
        </label>
        <label>
          <div className="label">Pembulatan jam lembur</div>
          <select className="input" value={form.overtime_rounding} onChange={(e) => set("overtime_rounding", e.target.value as PayrollSettings["overtime_rounding"])} style={{ width: "100%" }}>
            <option value="exact">Per menit</option>
            <option value="nearest_half">Ke 0,5 jam terdekat</option>
            <option value="down_half">Ke bawah per 0,5 jam</option>
            <option value="half_down">Blok 15/45 menit (1-15 = 0, 16-45 = 0,5, 46-60 = 1)</option>
          </select>
        </label>
        {number("overtime_min_minutes", "Lembur mulai dihitung setelah (menit)",
                "Dari jam pulang shift. 60 = lembur dihitung jika pulang jam 18:00 untuk shift 08-17")}
        <label>
          <div className="label">Batas lembur per hari kerja saat setujui massal (menit)</div>
          <input className="input" inputMode="numeric" placeholder="Tanpa batas" style={{ width: "100%" }}
                 value={form.overtime_daily_cap_minutes ?? ""}
                 onChange={(e) => {
                   const v = e.target.value.replace(/\D/g, "").slice(0, 4);
                   set("overtime_daily_cap_minutes", v === "" ? null : Number(v));
                 }} />
          <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 3 }}>
            Kosongkan (disarankan): lembur disetujui sesuai jam absen. PP 35/2021 membatasi lembur 4 jam per hari kerja,
            tetapi jam yang sudah dikerjakan tetap wajib dibayar. SeeGaji memberi peringatan, tidak memotong.
          </div>
          {err("overtime_daily_cap_minutes")}
        </label>
        {form.overtime_mode === "flat" && money("flat_overtime_hour", "Tarif per jam")}
        {form.overtime_mode === "flat" && money("flat_rest_day", "Tarif per hari libur", "Untuk kerja di hari libur / Minggu")}
      </Section>

      <Section title="Uang makan & keterlambatan">
        <label>
          <div className="label">Uang makan diberikan</div>
          <select className="input" value={form.meal_rule} onChange={(e) => set("meal_rule", e.target.value as PayrollSettings["meal_rule"])} style={{ width: "100%" }}>
            <option value="none">Tidak ada</option>
            <option value="overtime_day">Per hari lembur</option>
            <option value="present_day">Per hari hadir</option>
            <option value="late_out">Per hari pulang malam</option>
          </select>
        </label>
        {money("meal_allowance", "Uang makan per hari", "Juga untuk karyawan yang punya aturan uang makan sendiri (menu Karyawan)")}
        <label>
          <div className="label">Pulang malam mulai jam</div>
          <input className="input" type="time" value={(form.meal_late_after ?? "19:00").slice(0, 5)} style={{ width: "100%" }}
                 onChange={(e) => set("meal_late_after", e.target.value as never)} />
          <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 3 }}>Untuk aturan &quot;Per hari pulang malam&quot;</div>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
          <input type="checkbox" checked={!!form.meal_midnight_extra}
                 onChange={(e) => set("meal_midnight_extra", e.target.checked)} />
          Uang makan 1x lagi jika lembur lewat jam 00:00
        </label>
        {money("breakfast_allowance", "Uang sarapan", "0 = tidak ada")}
        <label>
          <div className="label">Sarapan jika masuk sebelum jam</div>
          <input className="input" type="time" value={(form.breakfast_before ?? "07:00").slice(0, 5)} style={{ width: "100%" }}
                 onChange={(e) => set("breakfast_before", e.target.value as never)} />
        </label>
        {money("late_fine_per_minute", "Potongan terlambat per menit", "0 = tidak dipotong. Harus tercantum di Peraturan Perusahaan / PKB.")}
        {number("late_tolerance_minutes", "Toleransi terlambat (menit)", "Dikurangi dari menit terlambat setiap hari")}
      </Section>

      <Section title="Lembur sampai lewat tengah malam"
               hint="Besoknya karyawan boleh masuk lebih siang tanpa dihitung terlambat. Dicek dari atas ke bawah terhadap jam pulang hari sebelumnya.">
        <div style={{ gridColumn: "1 / -1" }}>
          {nightRules.length === 0 && (
            <div style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 8 }}>Tidak dipakai: semua karyawan masuk sesuai jam shift.</div>
          )}
          {nightRules.map((r, i) => (
            <div key={i} style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 8, fontSize: 14 }}>
              <span style={{ minWidth: 130 }}>{i === 0 ? "Pulang 00:00 sampai" : "lalu sampai"}</span>
              <input className="input" type="time" value={r.until} style={{ width: 120 }}
                     onChange={(e) => setRule(i, { until: e.target.value })} />
              {r.until === "" && <span style={{ fontSize: 12.5, color: "var(--steel)" }}>(kosong = lebih dari itu)</span>}
              <span>→</span>
              <select className="input" value={r.start === "" ? "off" : "start"} style={{ width: 130 }}
                      onChange={(e) => setRule(i, { start: e.target.value === "off" ? "" : "10:00" })}>
                <option value="start">masuk jam</option>
                <option value="off">libur</option>
              </select>
              {r.start !== "" && (
                <input className="input" type="time" value={r.start} style={{ width: 120 }}
                       onChange={(e) => setRule(i, { start: e.target.value })} />
              )}
              <button type="button" className="btn-ghost" onClick={() => setRules(nightRules.filter((_, j) => j !== i))}>Hapus</button>
            </div>
          ))}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <button type="button" className="btn-ghost" onClick={() => setRules([...nightRules, { until: "", start: "" }])}>+ Tambah baris</button>
            <button type="button" className="btn-ghost" onClick={() => setRules(DKCB_NIGHT_RULES)}>Isi contoh (00:00-01:59 → 10:00, s/d 04:00 → 13:00, lebih → libur)</button>
            {nightRules.length > 0 && <button type="button" className="btn-ghost" onClick={() => setRules([])}>Matikan</button>}
          </div>
          {err("night_ot_rules")}
        </div>
      </Section>

      <Section title="BPJS Ketenagakerjaan & UMK" hint="JHT 2% dipotong dari karyawan; JHT 3,7%, JKK dan JKM ditanggung perusahaan.">
        <label>
          <div className="label">Kelompok risiko JKK</div>
          <select className="input" value={form.jkk_rate} onChange={(e) => set("jkk_rate", e.target.value)} style={{ width: "100%" }}>
            {JKK.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
          <input type="checkbox" checked={form.bpjs_base_includes_allowance}
                 onChange={(e) => set("bpjs_base_includes_allowance", e.target.checked)} />
          Upah BPJS = gaji pokok + tunjangan tetap
        </label>
        {money("minimum_wage", "UMK", "Untuk peringatan gaji di bawah UMK. 0 = tidak dicek.")}
      </Section>

      <Section title="Slip gaji" hint="Tampil di setiap slip yang dicetak.">
        <label style={{ gridColumn: "1 / -1" }}>
          <div className="label">Alamat perusahaan</div>
          <textarea className="input" rows={3} value={form.slip_address} onChange={(e) => set("slip_address", e.target.value)}
                    placeholder="Jln. Panca Marga, Sebong Pereh, Teluk Sebong, Kabupaten Bintan" style={{ width: "100%" }} />
        </label>
        <label>
          <div className="label">Tempat (di atas tanda tangan)</div>
          <input className="input" value={form.slip_place} onChange={(e) => set("slip_place", e.target.value)} placeholder="Bintan" style={{ width: "100%" }} />
        </label>
        <label>
          <div className="label">Penanda tangan perusahaan</div>
          <input className="input" value={form.slip_signer} onChange={(e) => set("slip_signer", e.target.value)} placeholder="HRD" style={{ width: "100%" }} />
        </label>
      </Section>

      {message && (
        <div style={{ background: message.ok ? "var(--workshop-lt)" : "var(--danger-light)", color: message.ok ? "var(--workshop)" : "var(--danger)",
                      padding: "10px 14px", borderRadius: 8, fontWeight: 600, fontSize: 14, marginBottom: 12 }}>{message.text}</div>
      )}
      <button className="btn-rust" onClick={save} disabled={busy} style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={15} />} Simpan pengaturan
      </button>
    </div>
  );
}
