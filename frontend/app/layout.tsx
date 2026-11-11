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
  title: "SeeGaji — Absensi ke Slip Gaji",
  description: "Dari mesin fingerprint ke slip gaji: absensi, lembur, uang makan, cuti, slip A5 dan file transfer bank dalam satu aplikasi.",
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
