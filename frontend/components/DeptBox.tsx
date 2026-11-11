"use client";
// =============================================================================
// DeptBox — which machine each Department in a combined file is read as (G12f.3.5, 11 Nov 2026).
// Used by both imports (taps, and HR's notes) when "Otomatis menurut Department" is chosen.
//
// Why: on 10 Nov Mesin Kantor's Department was typed "Staf Manager" (no comma). That is ONE label, so "Staf"
// and "Manager" belonged to no machine and four office people landed on plant IDs. HR can now fix it here:
//   - a label with a space whose words all appear on their own in the file → "Mungkin maksudnya 'Staf, Manager'?"
//     with a one-click fix;
//   - any Department read as Mesin utama ("semua yang lain") → "Bukan Mesin utama? Pindahkan ke …".
// Both save the machine's Department list and re-run the preview, so the name checks judge the result.
// DeptChips shows how a Department field is read, on Lokasi.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { Machine, machineApi } from "@/lib/api/machines";
import { Loader2 } from "lucide-react";
import { useState } from "react";

/** "Staf, Manager" → ["Staf", "Manager"]: split on commas, trimmed, each once (case ignored). */
export function deptLabels(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of (text || "").split(",")) {
    const label = raw.trim().replace(/\s+/g, " ");
    if (label && !seen.has(label.toLowerCase())) { seen.add(label.toLowerCase()); out.push(label); }
  }
  return out;
}

/** "Dibaca sebagai: [Staf] [Manager]": a missing comma shows up as one chip. */
export function DeptChips({ text }: { text: string }) {
  const labels = deptLabels(text);
  return (
    <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 4, display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
      {labels.length === 0 ? <span>Tidak ada Department.</span> : <>
        <span>Dibaca sebagai:</span>
        {labels.map((l) => (
          <span key={l} style={{ border: "1px solid var(--line)", borderRadius: 4, padding: "0 6px", background: "var(--paper)",
                                 color: "var(--ink)", fontWeight: 600 }}>{l}</span>
        ))}
        {labels.length === 1 && /\s/.test(labels[0]) && <span>(satu Department; pisahkan dengan koma kalau dua)</span>}
      </>}
    </div>
  );
}

export interface DeptRow { dept: string; people: number; taps?: number; machine: string; machine_key: string; claimed?: boolean }

interface Fix { machine: Machine; label: string; words: string[] }

/** A label with a space whose words all appear unclaimed in the file: probably a missing comma. */
function commaFixes(depts: DeptRow[], machines: Machine[]): Fix[] {
  const unclaimed = new Set(depts.filter((d) => d.claimed === false).map((d) => d.dept.trim().toLowerCase()));
  const fixes: Fix[] = [];
  for (const m of machines) {
    for (const label of deptLabels(m.dept_labels)) {
      const words = label.split(" ").filter(Boolean);
      if (words.length > 1 && words.every((w) => unclaimed.has(w.toLowerCase()))) fixes.push({ machine: m, label, words });
    }
  }
  return fixes;
}

export default function DeptBox({ depts, machines, unit, onChanged }: {
  depts: DeptRow[]; machines: Machine[]; unit?: "tap"; onChanged: (machines: Machine[]) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [moving, setMoving] = useState<string | null>(null);       // the Department whose "pindahkan" choice is open
  const fixes = commaFixes(depts, machines);
  const fixed = new Set(fixes.flatMap((f) => f.words.map((w) => w.toLowerCase())));

  const save = async (key: string, m: Machine, labels: string[]) => {
    setBusy(key);
    setError(null);
    try {
      const all = await machineApi.update(m.id, { dept_labels: labels.join(", ") });
      setMoving(null);
      onChanged(all);
    } catch (err) {
      const r = readErrors(err);
      setError(r.fields.dept_labels ?? r.summary);
    } finally {
      setBusy(null);
    }
  };
  const spin = { animation: "spin 1s linear infinite" };
  const link = { background: "none", border: "none", padding: 0, color: "var(--rust)", fontWeight: 600, cursor: "pointer", fontSize: 13 } as const;

  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "8px 12px", marginBottom: 12, fontSize: 13.5 }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>Department di file → mesin</div>

      {fixes.map((f) => (
        <div key={`${f.machine.id}-${f.label}`} style={{ background: "var(--hazard-light)", borderRadius: 6, padding: "8px 10px", margin: "4px 0 8px" }}>
          Di {f.machine.name}, Department tertulis <b>&quot;{f.label}&quot;</b> (satu nama), padahal file ini memakai{" "}
          {f.words.map((w) => `"${w}"`).join(" dan ")} terpisah. Mungkin maksudnya <b>&quot;{f.words.join(", ")}&quot;</b>?
          <div style={{ marginTop: 6 }}>
            <button className="btn-rust" disabled={busy !== null} style={{ padding: "6px 12px", fontSize: 13 }}
                    onClick={() => save(`fix-${f.machine.id}`, f.machine,
                      deptLabels(f.machine.dept_labels).flatMap((l) => (l === f.label ? f.words : [l])))}>
              {busy === `fix-${f.machine.id}` && <Loader2 size={14} style={spin} />} Ubah jadi &quot;{f.words.join(", ")}&quot; &amp; pratinjau lagi
            </button>
          </div>
        </div>
      ))}

      {depts.map((x) => (
        <div key={x.dept} style={{ padding: "2px 0" }}>
          {x.dept} → <b>{x.machine}</b> · {x.people} orang{unit === "tap" && x.taps != null ? ` · ${x.taps.toLocaleString("id-ID")} tap` : ""}
          {x.claimed === false && <span style={{ color: "var(--steel)" }}> (semua yang lain)</span>}
          {x.claimed === false && !fixed.has(x.dept.trim().toLowerCase()) && machines.length > 0 && (
            moving === x.dept ? (
              <span style={{ marginLeft: 8 }}>
                Pindahkan ke{" "}
                {machines.map((m, i) => (
                  <span key={m.id}>
                    {i > 0 && " · "}
                    <button style={link} disabled={busy !== null}
                            onClick={() => save(`move-${x.dept}`, m, [...deptLabels(m.dept_labels), x.dept.trim()])}>
                      {m.name}
                    </button>
                  </span>
                ))}
                {busy === `move-${x.dept}` && <Loader2 size={13} style={{ ...spin, marginLeft: 4 }} />}
                {" · "}<button style={{ ...link, color: "var(--steel)", fontWeight: 400 }} onClick={() => setMoving(null)}>batal</button>
              </span>
            ) : (
              <button style={{ ...link, marginLeft: 8, fontWeight: 400 }} onClick={() => setMoving(x.dept)}>Bukan Mesin utama?</button>
            )
          )}
        </div>
      ))}
      {error && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 4 }}>{error}</div>}
      <div style={{ color: "var(--steel)", fontSize: 12.5, marginTop: 4 }}>
        Department yang tidak terdaftar di mesin lain dibaca sebagai Mesin utama. Perubahan di sini tersimpan di
        Lokasi → Mesin fingerprint, lalu pratinjau diulang.
      </div>
    </div>
  );
}
