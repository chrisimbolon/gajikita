// SeeGaji wordmark: the "Si Mata" mark + "See" in Midnight (white on dark) + "Gaji" in Marigold.
import LogoMark from "@/components/LogoMark";

export default function Wordmark({ size = 22, onDark = false, mark = true }: { size?: number; onDark?: boolean; mark?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: Math.round(size * 0.4) }}>
      {mark && <LogoMark size={Math.round(size * 1.45)} onDark={onDark} />}
      <div style={{ fontSize: size, fontWeight: 800, letterSpacing: "-0.02em", color: onDark ? "#FFFFFF" : "var(--midnight)" }}>
        See<span style={{ color: "var(--marigold)" }}>Gaji</span>
      </div>
    </div>
  );
}
