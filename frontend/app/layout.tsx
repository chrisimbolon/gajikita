import { AuthProvider } from "@/context/AuthContext";
import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";

// Plus Jakarta Sans: made by an Indonesian type studio for Jakarta. next/font downloads
// it at build time and serves it from our own site, so phones never wait on Google.
const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "GajiKita — Absensi, Gaji & Pajak Karyawan",
  description: "Absensi, cuti, gaji, BPJS dan PPh 21 karyawan dalam satu aplikasi.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" className={jakarta.variable}>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
