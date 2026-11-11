"use client";
// =============================================================================
// ExemptionCard — "Tidak wajib absen" on the Karyawan panel (G12i, 11 Nov 2026).
// For people paid every working day without tapping: off-site with no machine (DKCB: Marganda, "Kerja di
// Lobam") or a role that doesn't tap (sales). A dated period with a reason; saved straight away (not with the
// panel's Simpan), audited, and refused when it would change a locked payroll. Ending a period changes only
// the days after its new end, never a month already paid.
// =============================================================================
import { Exemption, exemptionApi } from "@/lib/api/exemptions";
import { readErrors } from "@/lib/api/hr";
import { todayISO } from "@/lib/format";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

function d(iso: string | null): string {
  if (!iso) return "seterusnya";
  const [y, m, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("id-ID", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" })
    .format(new Date(Date.UTC(y, m - 1, day)));
}

export default function ExemptionCard({ employeeId, onChanged }: {
  employeeId: string; onChanged: (current: Exemption | null) => void;
}) {
  const [list, setList] = useState<Exemption[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [start, setStart] = useState(todayISO());
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const [ending, setEnding] = useState<string | null>(null);        // id of the period being ended
  const [removing, setRemoving] = useState<string | null>(null);    // id of the period about to be deleted
  const [endDate, setEndDate] = useState(todayISO());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    exemptionApi.list(employeeId).then((r) => setList(r.exemptions)).catch(() => setList([]));
  }, [employeeId]);

  const apply = async (call: () => Promise<{ exemptions: Exemption[]; current: Exemption | null }>) => {
    setBusy(true);
    setError(null);
    try {
      const r = await call();
      setList(r.exemptions);
      onChanged(r.current);
      setAdding(false);
      setEnding(null);
      setRemoving(null);
      setReason("");
      setEnd("");
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  if (list === null) return null;
  const spin = { animation: "spin 1s linear infinite" };

  return (
    <div style={{ marginBottom: 12 }}>
      <label className="label">Tidak wajib absen</label>
      <div style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 6 }}>
        Untuk karyawan yang bekerja di tempat tanpa mesin (mis. di proyek lain) atau yang memang tidak absen (mis. sales).
        Selama periode ini setiap hari kerja dihitung <b>hadir</b> (kode <b>DL</b> di Rekap): tanpa denda telat, tanpa lembur
        dan uang makan otomatis. Cuti tetap dicatat. Langsung tersimpan.
      </div>

      {list.length === 0 && !adding && <div style={{ fontSize: 13, color: "var(--steel)" }}>Tidak ada. Karyawan ini wajib absen.</div>}
      {list.map((x) => (
        <div key={x.id} style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "8px 10px", marginBottom: 6, fontSize: 13.5 }}>
          <div><b>{d(x.start)} – {d(x.end)}</b> · {x.reason}</div>
          {ending === x.id ? (
            <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 6, flexWrap: "wrap" }}>
              <span>Hari terakhir tidak wajib absen:</span>
              <input className="input" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} style={{ width: "auto" }} />
              <button className="btn-rust" disabled={busy || !endDate} onClick={() => apply(() => exemptionApi.update(x.id, { end: endDate }))}>
                {busy && <Loader2 size={14} style={spin} />} Simpan
              </button>
              <button className="btn-ghost" onClick={() => setEnding(null)}>Batal</button>
            </div>
          ) : (
            <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
              {!x.end && <button onClick={() => { setEnding(x.id); setEndDate(todayISO()); }}
                                 style={{ background: "none", border: "none", padding: 0, color: "var(--rust)", fontWeight: 600, cursor: "pointer", fontSize: 13 }}>
                Akhiri (sudah kembali absen)
              </button>}
              {removing === x.id ? (
                <span style={{ fontSize: 13 }}>
                  Hapus periode ini? Hari-harinya kembali dihitung dari tap.{" "}
                  <button onClick={() => apply(() => exemptionApi.remove(x.id))} disabled={busy}
                          style={{ background: "none", border: "none", padding: 0, color: "var(--danger)", fontWeight: 700, cursor: "pointer", fontSize: 13 }}>
                    Ya, hapus
                  </button>{" · "}
                  <button onClick={() => setRemoving(null)}
                          style={{ background: "none", border: "none", padding: 0, color: "var(--steel)", cursor: "pointer", fontSize: 13 }}>
                    Batal
                  </button>
                </span>
              ) : (
                <button onClick={() => setRemoving(x.id)}
                        style={{ background: "none", border: "none", padding: 0, color: "var(--steel)", cursor: "pointer", fontSize: 13 }}>
                  Hapus (salah isi)
                </button>
              )}
            </div>
          )}
        </div>
      ))}

      {adding ? (
        <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: 10, background: "var(--paper)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 10px" }}>
            <div><label className="label">Mulai</label>
              <input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></div>
            <div><label className="label">Sampai (kosong = seterusnya)</label>
              <input className="input" type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
          </div>
          <label className="label" style={{ marginTop: 8 }}>Alasan</label>
          <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="mis. Kerja di Lobam, Sales lapangan" />
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="btn-rust" disabled={busy || !start || reason.trim().length < 3}
                    onClick={() => apply(() => exemptionApi.create(employeeId, { start, end: end || null, reason }))}>
              {busy && <Loader2 size={14} style={spin} />} Simpan periode
            </button>
            <button className="btn-ghost" onClick={() => { setAdding(false); setError(null); }}>Batal</button>
          </div>
        </div>
      ) : (
        <button className="btn-ghost" onClick={() => { setAdding(true); setStart(todayISO()); }} style={{ fontSize: 13.5, marginTop: 4 }}>
          + Tambah periode tidak wajib absen
        </button>
      )}
      {error && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 6 }}>{error}</div>}
    </div>
  );
}
