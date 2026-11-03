// =============================================================================
// AbsensiTabs — "Harian | Rekap periode" on top of the Absensi pages (G10, 1 Nov 2026).
// =============================================================================
import Link from "next/link";

export default function AbsensiTabs({ active }: { active: "harian" | "rekap" }) {
  const tab = (key: "harian" | "rekap", href: string, label: string) => (
    <Link href={href} style={{
      padding: "7px 16px", fontSize: 14, fontWeight: 700, borderRadius: 999, textDecoration: "none",
      background: active === key ? "var(--midnight)" : "transparent",
      color: active === key ? "#fff" : "var(--steel)",
    }}>{label}</Link>
  );
  return (
    <div style={{ display: "inline-flex", gap: 4, padding: 3, border: "1px solid var(--line)", borderRadius: 999, marginBottom: 14 }}>
      {tab("harian", "/dashboard/absensi", "Harian")}
      {tab("rekap", "/dashboard/absensi/rekap", "Rekap periode")}
    </div>
  );
}
