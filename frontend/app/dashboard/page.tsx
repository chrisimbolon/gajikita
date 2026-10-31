"use client";
// =============================================================================
// /dashboard — Ringkasan (G6, 28 Oct 2026), the "Arah A" design made real:
// the one thing that needs HR (Marigold), today's counts, today's list with
// problems first, and this month's approved overtime per site (Midnight panel).
// =============================================================================
import { StatusPill } from "@/components/DayPanel";
import { minutesText } from "@/lib/api/attendance";
import { Summary, dashboardApi } from "@/lib/api/dashboard";
import { readErrors } from "@/lib/api/hr";
import { rupiah } from "@/lib/format";
import { CalendarOff, CheckCircle2, ChevronRight, Clock, Loader2, MapPin, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const WIB = "Asia/Jakarta";

function greeting(): string {
  const h = Number(new Intl.DateTimeFormat("en-GB", { timeZone: WIB, hour: "2-digit", hourCycle: "h23" }).format(new Date()));
  if (h < 11) return "Selamat pagi";
  if (h < 15) return "Selamat siang";
  if (h < 18) return "Selamat sore";
  return "Selamat malam";
}

function longDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("id-ID", { timeZone: "UTC", weekday: "long", day: "numeric", month: "long", year: "numeric" })
    .format(new Date(Date.UTC(y, m - 1, d)));
}

function monthName(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Intl.DateTimeFormat("id-ID", { timeZone: "UTC", month: "long", year: "numeric" }).format(new Date(Date.UTC(y, m - 1, 1)));
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

const card = { background: "#FFFFFF", border: "1px solid #D5E0E8", borderRadius: 16 } as const;

export default function RingkasanPage() {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dashboardApi.summary().then(setData).catch((err) => setError(readErrors(err).summary));
  }, []);

  if (error) return <div className="card" style={{ color: "var(--danger)" }}>{error}</div>;
  if (!data) return <div style={{ padding: 24, color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>;

  const firstName = data.user_name.split(" ")[0] || data.user_name;
  const c = data.counters;
  const stats = [
    { label: "Hadir", value: data.present, dot: "var(--workshop)" },
    { label: "Terlambat", value: c.late ?? 0, dot: "#C77700" },
    { label: "Tidak absen pulang", value: c.no_clock_out ?? 0, dot: "var(--danger)" },
    { label: "Tidak hadir", value: c.absent ?? 0, dot: "var(--danger)" },
    { label: "Cuti / izin", value: c.leave ?? 0, dot: "var(--midnight)" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 1180 }}>
      <div>
        <h1 className="display" style={{ fontSize: 30, margin: 0 }}>{greeting()}, {firstName}</h1>
        <div style={{ color: "var(--steel)", fontSize: 14.5, marginTop: 4 }}>
          {longDate(data.date)} · {data.employees_active} karyawan aktif di {data.sites_active} lokasi
        </div>
      </div>

      {data.employees_active === 0 ? (
        <div style={{ ...card, padding: 24 }}>
          <div style={{ fontSize: 18, fontWeight: 800, color: "var(--midnight)" }}>Mulai di sini</div>
          <div style={{ color: "var(--steel)", fontSize: 14, margin: "4px 0 16px" }}>Tiga langkah sebelum karyawan bisa absen dari HP.</div>
          {[{ href: "/dashboard/lokasi", icon: MapPin, title: "1. Tambah lokasi kerja", text: "Taruh titik di peta dan atur radiusnya." },
            { href: "/dashboard/shift", icon: Clock, title: "2. Buat shift", text: "Jam masuk, jam pulang, toleransi terlambat." },
            { href: "/dashboard/karyawan", icon: Users, title: "3. Tambah karyawan", text: "Lalu aktifkan login HP dan berikan PIN-nya." }].map((s) => (
            <Link key={s.href} href={s.href} style={{ display: "flex", gap: 14, alignItems: "center", padding: "12px 0", borderTop: "1px solid #E6EDF2",
                                                    textDecoration: "none", color: "var(--ink)" }}>
              <s.icon size={20} style={{ color: "var(--midnight)" }} />
              <div><div style={{ fontWeight: 700 }}>{s.title}</div><div style={{ fontSize: 13.5, color: "var(--steel)" }}>{s.text}</div></div>
            </Link>
          ))}
        </div>
      ) : (
        <>
          {/* the one thing that needs attention: the Marigold tile */}
          <div style={{ ...card, display: "flex", alignItems: "center", gap: 18, padding: "16px 18px" }}>
            {data.review.count > 0 ? (
              <div style={{ width: 64, height: 64, borderRadius: 14, background: "var(--marigold)", color: "var(--midnight)", flexShrink: 0,
                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 30, fontWeight: 800 }}>
                {data.review.count}
              </div>
            ) : (
              <div style={{ width: 64, height: 64, borderRadius: 14, background: "var(--workshop-lt)", flexShrink: 0,
                            display: "flex", alignItems: "center", justifyContent: "center" }}>
                <CheckCircle2 size={30} style={{ color: "var(--workshop)" }} />
              </div>
            )}
            <div style={{ flexGrow: 1 }}>
              <div style={{ fontSize: 17, fontWeight: 800, color: "var(--midnight)" }}>
                {data.review.count > 0 ? "Perlu tindakan" : "Semua beres"}
              </div>
              <div style={{ fontSize: 14, color: "var(--steel)", marginTop: 2 }}>
                {data.review.count > 0
                  ? data.review.summary.map((s) => `${s.count} ${s.label.toLowerCase()}`).join(" · ") + " · 7 hari terakhir"
                  : "Tidak ada absen yang perlu ditinjau dalam 7 hari terakhir."}
              </div>
            </div>
            {data.review.count > 0 && (
              <Link href="/dashboard/absensi/tinjau" className="btn-rust" style={{ textDecoration: "none", padding: "11px 18px" }}>Tinjau sekarang</Link>
            )}
          </div>

          {data.leave.pending > 0 && (
            <Link href="/dashboard/cuti" style={{ ...card, display: "flex", alignItems: "center", gap: 12, padding: "12px 18px",
                                                  textDecoration: "none", color: "var(--ink)" }}>
              <CalendarOff size={20} style={{ color: "var(--midnight)" }} />
              <div style={{ flexGrow: 1, fontSize: 14 }}>
                <b>{data.leave.pending} pengajuan cuti / izin</b> menunggu persetujuan atasan atau HR
              </div>
              <ChevronRight size={18} style={{ color: "var(--steel)" }} />
            </Link>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 12 }}>
            {stats.map((s) => (
              <Link key={s.label} href="/dashboard/absensi" style={{ ...card, padding: "14px 16px", textDecoration: "none", color: "var(--ink)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13, color: "var(--steel)" }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: s.dot }} />{s.label}
                </div>
                <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.02em", marginTop: 4 }}>{s.value}</div>
              </Link>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.75fr) minmax(0, 1fr)", gap: 14, alignItems: "start" }}>
            <div style={{ ...card, overflow: "hidden" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 18px 10px" }}>
                <div style={{ fontSize: 15, fontWeight: 800, color: "var(--midnight)" }}>Absensi hari ini</div>
                <Link href="/dashboard/absensi" style={{ fontSize: 13, fontWeight: 600 }}>
                  Lihat semua{data.today_total > data.today.length ? ` (${data.today_total})` : ""}
                </Link>
              </div>
              {data.today.map((r) => (
                <div key={r.employee.id} style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.6fr) minmax(0, 1.3fr) 60px 60px",
                                                  gap: 10, alignItems: "center", padding: "11px 18px", borderTop: "1px solid #E6EDF2", fontSize: 13.5 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                    <div style={{ width: 32, height: 32, borderRadius: "50%", background: "var(--midnight-soft)", color: "var(--midnight)", flexShrink: 0,
                                  fontSize: 11.5, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      {initials(r.employee.full_name)}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.employee.full_name}</div>
                      <div style={{ fontSize: 12, color: "var(--steel)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {Object.keys(r.site_minutes)[0] ?? r.employee.employee_no}
                      </div>
                    </div>
                  </div>
                  <div><StatusPill status={r.status} label={r.status === "late" ? `Terlambat ${r.late_minutes} mnt` : r.status_label} /></div>
                  <div className="mono">{r.first_in ?? "-"}</div>
                  <div className="mono" style={{ color: "var(--steel)" }}>{r.last_out ?? "-"}</div>
                </div>
              ))}
            </div>

            {/* this month's approved overtime: the Midnight panel */}
            <Link href="/dashboard/lembur" style={{ background: "var(--midnight)", color: "#FFFFFF", borderRadius: 16, padding: 18, textDecoration: "none",
                                                   display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 13, color: "var(--on-dark-muted)", fontWeight: 600 }}>Lembur disetujui · {monthName(data.overtime.month)}</div>
              <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.02em" }}>{rupiah(data.overtime.amount)}</div>
              <div style={{ fontSize: 13, color: "var(--on-dark-muted)" }}>
                {minutesText(data.overtime.minutes)} · {data.overtime.people} karyawan · sesuai PP 35/2021
              </div>
              {data.overtime.sites.length === 0 ? (
                <div style={{ fontSize: 13, color: "var(--on-dark-muted)" }}>Belum ada lembur yang disetujui bulan ini.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 2 }}>
                  {data.overtime.sites.map((s) => (
                    <div key={s.site}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 4, gap: 8 }}>
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.site}</span>
                        <span style={{ fontWeight: 700, whiteSpace: "nowrap" }}>{rupiah(s.amount)}</span>
                      </div>
                      <div style={{ height: 8, borderRadius: 999, background: "rgba(255,255,255,0.14)" }}>
                        <div style={{ height: 8, borderRadius: 999, width: `${Math.max(4, s.share)}%`, background: "var(--marigold)" }} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
