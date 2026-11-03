// GajiKita wordmark: "Gaji" in Midnight (white on dark), "Kita" in Marigold.
export default function Wordmark({ size = 22, onDark = false }: { size?: number; onDark?: boolean }) {
  return (
    <div style={{ fontSize: size, fontWeight: 800, letterSpacing: "-0.02em", color: onDark ? "#FFFFFF" : "var(--midnight)" }}>
      Gaji<span style={{ color: "var(--marigold)" }}>Kita</span>
    </div>
  );
}
