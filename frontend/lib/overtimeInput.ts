// =============================================================================
// === frontend/lib/overtimeInput.ts ===
// G17-6 (15 Nov 2026): the "Lembur dibayar" box in Tinjau per periode. HR types hours the way the SPL and the
// book write them: "2", "2,5", "2.5", "1:30", "0". Kept in minutes underneath.
// =============================================================================

/** Minutes for the box: 210 -> "3:30", 480 -> "8", 0 -> "0". */
export function hoursText(minutes: number | null | undefined): string {
  const m = Math.max(0, Math.round(minutes ?? 0));
  const h = Math.floor(m / 60), r = m % 60;
  return r ? `${h}:${String(r).padStart(2, "0")}` : String(h);
}

/** What HR typed -> minutes, or null when it is not a number of hours (then the button stays off). */
export function parseHours(text: string): number | null {
  const t = text.trim().replace(",", ".");
  if (t === "") return null;
  const hm = /^(\d{1,2}):([0-5]\d)$/.exec(t);
  if (hm) return Number(hm[1]) * 60 + Number(hm[2]);
  if (!/^\d{1,2}(\.\d{1,2})?$/.test(t)) return null;
  const minutes = Math.round(Number(t) * 60);
  return minutes <= 24 * 60 ? minutes : null;
}
