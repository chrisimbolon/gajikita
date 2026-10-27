import { AuthProvider } from "@/context/AuthContext";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GajiKita — Absensi, Gaji & Pajak Karyawan",
  description: "Absensi, cuti, gaji, BPJS dan PPh 21 karyawan dalam satu aplikasi.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
