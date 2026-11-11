"use client";
// seegaji.com/ — the public landing page. Logged in: its buttons say "Buka SeeGaji" and go to the app
// (HR → /dashboard, karyawan → /absen). Logged out: "Masuk" → /login.
import Landing from "@/components/landing/Landing";
import { useAuth } from "@/context/AuthContext";

export default function Home() {
  const { user, loading } = useAuth();
  const appHref = loading || !user ? null : user.role === "employee" ? "/absen" : "/dashboard";
  return <Landing appHref={appHref} />;
}
