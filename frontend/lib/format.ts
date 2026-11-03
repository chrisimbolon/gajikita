// =============================================================================
// === frontend/lib/format.ts ===
// Dates and numbers, always in WIB / Indonesian style.
// =============================================================================
const WIB = "Asia/Jakarta";

/** Today's date in Jakarta as YYYY-MM-DD (never the UTC day; see scripts/check-no-utc-dates.js). */
export function todayISO(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: WIB, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date());
}

export function dateTimeWIB(iso: string): string {
  return new Intl.DateTimeFormat("id-ID", {
    timeZone: WIB, day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));
}

export function rupiah(value: string | number): string {
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "-";
  return "Rp " + new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(n);
}

/** "08:00:00" -> "08:00" */
export function hhmm(time: string): string {
  return (time || "").slice(0, 5);
}

export const DAY_NAMES = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"] as const;   // 1..7
