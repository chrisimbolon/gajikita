"use client";
// The office sidebar: Midnight, with the active page lifted and the
// review count in Marigold (theme "Arah A", 28 Oct 2026).
import Wordmark from "@/components/Wordmark";
import { useAuth } from "@/context/AuthContext";
import { CalendarCheck, CalendarOff, ClipboardCheck, Clock, KeyRound, LayoutDashboard, LogOut, MapPin, Timer, UserCog, Users, Wallet,
         Zap } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/dashboard", icon: LayoutDashboard, label: "Ringkasan" },
  { href: "/dashboard/absensi", icon: CalendarCheck, label: "Absensi" },
  { href: "/dashboard/absensi/tinjau", icon: ClipboardCheck, label: "Perlu Tinjau" },
  { href: "/dashboard/absensi/kejadian", icon: Zap, label: "Kejadian" },                  // G17-2
  { href: "/dashboard/lembur", icon: Timer, label: "Lembur" },
  { href: "/dashboard/cuti", icon: CalendarOff, label: "Cuti & Izin" },
  { href: "/dashboard/payroll", icon: Wallet, label: "Payroll" },
  { href: "/dashboard/karyawan", icon: Users, label: "Karyawan" },
  { href: "/dashboard/lokasi", icon: MapPin, label: "Lokasi" },
  { href: "/dashboard/shift", icon: Clock, label: "Shift" },
];
// G22-1: only an owner or admin manages the company's office users
const MANAGER_NAV = [{ href: "/dashboard/pengguna", icon: UserCog, label: "Pengguna" }];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, organization, orgRole, logout } = useAuth();
  const nav = orgRole === "owner" || orgRole === "admin" ? [...NAV, ...MANAGER_NAV] : NAV;

  return (
    <aside style={{ width: 236, minHeight: "100vh", background: "var(--midnight)", color: "#FFFFFF", display: "flex",
                    flexDirection: "column", padding: "26px 16px", flexShrink: 0 }}>
      <div style={{ padding: "0 10px", marginBottom: 24 }}><Wordmark size={24} onDark /></div>
      {organization && (
        <div style={{ padding: "10px 12px", background: "rgba(255,255,255,0.08)", borderRadius: 12, marginBottom: 22 }}>
          <div style={{ fontSize: 10.5, color: "var(--on-dark-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>
            Perusahaan aktif
          </div>
          <div style={{ fontSize: 13.5, fontWeight: 700 }}>{organization.name}</div>
        </div>
      )}
      <nav aria-label="Menu utama" style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
        {nav.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined} style={{
              display: "flex", alignItems: "center", gap: 11, padding: "10px 12px", borderRadius: 10, textDecoration: "none",
              fontSize: 14, fontWeight: active ? 700 : 500,
              color: active ? "#FFFFFF" : "#C9DAE4",
              background: active ? "rgba(255,255,255,0.12)" : "transparent",
            }}>
              <Icon size={17} /> {item.label}
            </Link>
          );
        })}
      </nav>
      <div style={{ borderTop: "1px solid rgba(255,255,255,0.12)", paddingTop: 16, marginTop: 16 }}>
        <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 2, padding: "0 4px" }}>{user?.full_name}</div>
        <div style={{ fontSize: 12, color: "var(--on-dark-muted)", marginBottom: 8, padding: "0 4px" }}>{user?.email}</div>
        <Link href="/dashboard/akun" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600,
                                              color: "#C9DAE4", textDecoration: "none", padding: "0 4px", marginBottom: 12 }}>
          <KeyRound size={13} /> Akun saya · ubah password
        </Link>
        <button onClick={logout} style={{ width: "100%", display: "flex", justifyContent: "center", alignItems: "center", gap: 7,
                                          fontSize: 13, fontWeight: 700, color: "#FFFFFF", background: "rgba(255,255,255,0.10)",
                                          border: "1px solid rgba(255,255,255,0.18)", borderRadius: 10, padding: "9px 0" }}>
          <LogOut size={14} /> Keluar
        </button>
      </div>
    </aside>
  );
}
