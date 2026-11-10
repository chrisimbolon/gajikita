"use client";
// =============================================================================
// HrNote — HR's own note for a day, from the imported recap (G12f.3.2, 10 Nov 2026).
// The code is drawn in the colour HR used in the file ("UL" on yellow, "Lain" on blue), so it
// looks like the workbook HR knows. A note is shown only: it never changes a status or a number.
// =============================================================================
import { HrNote } from "@/lib/api/attendance";

/** Dark or white text, whichever reads better on the fill. */
export function inkOn(hex: string): string {
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) return "var(--ink)";
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.55 ? "#1F2933" : "#FFFFFF";
}

export function noteTitle(note: HrNote): string {
  return `Catatan HR${note.code ? ` (${note.code})` : ""}: ${note.text || "-"}`;
}

/** The text, unless it only repeats the code ("UL" written in a yellow "UL" cell). */
function extraText(note: HrNote): string {
  return note.text && note.text.trim().toLowerCase() !== note.code.trim().toLowerCase() ? note.text : "";
}

export function NoteCode({ code, color, count, title }: { code: string; color: string; count?: number; title?: string }) {
  return (
    <span title={title} style={{ display: "inline-block", background: color ? `#${color}` : "var(--paper-2)",
                                 color: color ? inkOn(color) : "var(--ink)", fontWeight: 800, fontSize: 11.5, borderRadius: 4,
                                 padding: "0 6px", border: "1px solid rgba(0,0,0,0.12)", whiteSpace: "nowrap", lineHeight: "18px" }}>
      {code || "Catatan"}{count != null ? ` × ${count}` : ""}
    </span>
  );
}

/** One line for tables: the code chip, then the text (cut with "…" when maxWidth is given). */
export function HrNoteLine({ note, maxWidth }: { note: HrNote; maxWidth?: number }) {
  const text = extraText(note);
  return (
    <span title={noteTitle(note)} style={{ display: "inline-flex", alignItems: "center", gap: 6, maxWidth, verticalAlign: "middle" }}>
      <NoteCode code={note.code} color={note.color} />
      {text && <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--ink-soft)", fontSize: 12.5 }}>{text}</span>}
    </span>
  );
}

/** The box in the day panel. */
export function HrNoteBox({ note }: { note: HrNote }) {
  const text = extraText(note);
  return (
    <div style={{ border: "1px solid var(--line)", borderLeft: `4px solid ${note.color ? `#${note.color}` : "var(--steel)"}`,
                  borderRadius: 6, padding: "8px 12px", fontSize: 13.5, marginBottom: 12, background: "var(--paper)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700 }}>
        Catatan HR <NoteCode code={note.code} color={note.color} />
      </div>
      {text && <div style={{ marginTop: 4 }}>{text}</div>}
      <div style={{ color: "var(--steel)", fontSize: 12, marginTop: 4 }}>
        Dari file rekap HR. Hanya keterangan: status, jam dan gaji tidak berubah karena catatan ini.
      </div>
    </div>
  );
}
