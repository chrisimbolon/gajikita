// The worker's phone pages (/absen, /absen/masuk, /absen/pin): one narrow
// column, big touch targets, no office sidebar.
export default function AbsenLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", justifyContent: "center", background: "var(--paper)" }}>
      <div style={{ width: "100%", maxWidth: 460, padding: "20px 16px 40px" }}>{children}</div>
    </div>
  );
}
