"use client";
// =============================================================================
// DayPanel — one employee's day for HR (G3, 28 Oct 2026). Used by the daily
// attendance page and the review queue. Shows every tap (selfie, site,
// distance, GPS accuracy, flags), the minutes, and HR's three actions:
// Setujui (approve), Tolak (reject), Ubah jam (fix times). Every action
// lands in the audit log at the bottom.
// =============================================================================
import { DayDetail, DayRow, STATUS_STYLE, attendanceApi, minutesText } from "@/lib/api/attendance";
import { readErrors } from "@/lib/api/hr";
import { dateTimeWIB, rupiah } from "@/lib/format";
import { Check, Clock, ExternalLink, Fingerprint, Loader2, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";

type Mode = null | "approve" | "reject" | "fix";

export function StatusPill({ status, label }: { status: DayRow["status"]; label: string }) {
  const s = STATUS_STYLE[status];
  return <span className="pill" style={{ background: s.bg, color: s.fg }}>{label}</span>;
}

function SelfieThumb({ eventId }: { eventId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [big, setBig] = useState(false);
  useEffect(() => {
    let alive = true, made: string | null = null;
    attendanceApi.selfieUrl(eventId).then((u) => { made = u; if (alive) setUrl(u); else URL.revokeObjectURL(u); })
      .catch(() => { /* no picture: leave the placeholder */ });
    return () => { alive = false; if (made) URL.revokeObjectURL(made); };
  }, [eventId]);
  if (!url) return <div style={{ width: 56, height: 56, borderRadius: 6, background: "var(--paper-2)" }} />;
  return (
    <>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt="Selfie" onClick={() => setBig(true)}
           style={{ width: 56, height: 56, objectFit: "cover", borderRadius: 6, cursor: "zoom-in" }} />
      {big && (
        <div onClick={() => setBig(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", zIndex: 50,
                                                    display: "flex", alignItems: "center", justifyContent: "center", cursor: "zoom-out" }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={url} alt="Selfie" style={{ maxWidth: "90vw", maxHeight: "85vh", borderRadius: 8 }} />
        </div>
      )}
    </>
  );
}

interface Props {
  row:       DayRow;
  onChanged: (row: DayRow) => void;
  onClose:   () => void;
}

export default function DayPanel({ row, onChanged, onClose }: Props) {
  const [detail, setDetail] = useState<DayDetail | null>(null);
  const [loading, setLoading] = useState(!!row.day_id);
  const [mode, setMode] = useState<Mode>(row.day_id ? null : "fix");
  const [note, setNote] = useState("");
  const [waiveLate, setWaiveLate] = useState(false);
  const [overtime, setOvertime] = useState<number>(row.overtime_proposed_minutes);
  const [clockIn, setClockIn] = useState(row.first_in ?? "");
  const [clockOut, setClockOut] = useState(row.last_out ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!row.day_id) return;
    attendanceApi.day(row.day_id).then((d) => { setDetail(d); setOvertime(d.overtime_approved_minutes ?? d.overtime_proposed_minutes); })
      .catch((err) => setError(readErrors(err).summary)).finally(() => setLoading(false));
  }, [row.day_id]);

  const view: DayRow = detail ?? row;
  const locked = view.is_locked;

  const done = (d: DayDetail) => {
    setDetail(d); setMode(null); setNote(""); setError(null);
    onChanged(d);
  };

  const run = async (fn: () => Promise<DayDetail>) => {
    setBusy(true); setError(null);
    try { done(await fn()); } catch (err) { setError(readErrors(err).summary); } finally { setBusy(false); }
  };

  const approve = () => run(() => attendanceApi.decide(view.day_id!, {
    action: "approve", note, waive_late: waiveLate, overtime_minutes: view.overtime_proposed_minutes ? overtime : null,
  }));
  const reject = () => run(() => attendanceApi.decide(view.day_id!, { action: "reject", note }));
  const reset = () => run(() => attendanceApi.decide(view.day_id!, { action: "reset" }));
  const fix = () => run(() => attendanceApi.fix({
    employee: view.employee.id, date: view.date, clock_in: clockIn || null, clock_out: clockOut || null, reason: note,
  }));

  const fact = (label: string, value: string) => (
    <div><div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
      <div style={{ fontWeight: 600, fontSize: 14.5 }}>{value}</div></div>
  );

  return (
    <div className="card" style={{ position: "sticky", top: 20, maxHeight: "calc(100vh - 40px)", overflowY: "auto", padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 17 }}>{view.employee.full_name}</div>
          <div className="mono" style={{ fontSize: 12.5, color: "var(--steel)" }}>
            {view.employee.employee_no} · {view.date}{detail?.shift ? ` · ${detail.shift.name} ${detail.shift.start}-${detail.shift.end}` : ""}
          </div>
        </div>
        <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none", color: "var(--steel)" }}><X size={18} /></button>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 14 }}>
        <StatusPill status={view.status} label={view.status_label} />
        {view.decision === "approved" && <span className="pill ok"><span className="dot" />Disetujui HR</span>}
        {view.hr_fixed && <span className="pill soon">Jam dikoreksi HR</span>}
        {locked && <span className="pill" style={{ background: "var(--paper-2)" }}>Terkunci</span>}
      </div>

      {loading ? <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 14 }}>
            {fact("Masuk", view.first_in ?? "-")}
            {fact("Pulang", view.last_out ?? "-")}
            {fact("Jam kerja", minutesText(view.worked_minutes))}
            {fact("Terlambat", minutesText(view.late_minutes))}
            {fact("Pulang cepat", minutesText(view.early_minutes))}
            {fact("Lembur", view.overtime_approved_minutes != null ? `${minutesText(view.overtime_approved_minutes)} (disetujui)`
              : view.overtime_proposed_minutes ? `${minutesText(view.overtime_proposed_minutes)} (usulan)` : "-")}
          </div>

          {detail?.overtime_pay && (
            <div style={{ background: "var(--paper)", borderRadius: 6, padding: "10px 12px", fontSize: 13.5, marginBottom: 14 }}>
              {"not_paid" in detail.overtime_pay ? (
                <span style={{ color: "var(--steel)" }}>Upah lembur: {detail.overtime_pay.not_paid}</span>
              ) : (
                <>
                  <b>Upah lembur{detail.overtime_pay.estimate ? " (perkiraan, belum disetujui)" : ""}: {rupiah(detail.overtime_pay.amount)}</b>
                  {detail.overtime_pay.mode === "flat" ? (
                    <>
                      <div style={{ color: "var(--steel)", fontSize: 12.5, marginTop: 2 }}>
                        Tarif perusahaan · {detail.overtime_pay.rest_day ? `hari libur ${rupiah(detail.overtime_pay.rate ?? "0")}`
                          : `${minutesText(detail.overtime_pay.rounded_minutes ?? 0)} × ${rupiah(detail.overtime_pay.rate ?? "0")}/jam`}
                      </div>
                      {detail.overtime_pay.pp35_amount && (
                        <div style={{ fontSize: 12.5, marginTop: 4, color: Number(detail.overtime_pay.gap) > 0 ? "var(--hazard-dark)" : "var(--steel)" }}>
                          Menurut PP 35/2021: {rupiah(detail.overtime_pay.pp35_amount)}
                          {Number(detail.overtime_pay.gap) > 0 && <> · kurang {rupiah(detail.overtime_pay.gap ?? "0")}</>}
                        </div>
                      )}
                    </>
                  ) : (
                    <div style={{ color: "var(--steel)", fontSize: 12.5, marginTop: 2 }}>
                      {detail.overtime_pay.rest_day ? "Hari libur" : "Hari kerja"} · upah per jam {rupiah(detail.overtime_pay.hourly_rate)} ·{" "}
                      {detail.overtime_pay.lines.map((l) => `${minutesText(l.minutes)} × ${l.multiplier.replace(".", ",")}`).join(" + ")}
                    </div>
                  )}
                  {detail.overtime_pay.warnings.map((w) => <div key={w} style={{ color: "var(--hazard-dark)", fontSize: 12.5 }}>{w}</div>)}
                </>
              )}
            </div>
          )}

          {Object.keys(view.site_minutes).length > 1 && (
            <div style={{ fontSize: 13, color: "var(--ink-soft)", marginBottom: 12 }}>
              Per lokasi: {Object.entries(view.site_minutes).map(([s, m]) => `${s} ${minutesText(m)}`).join(" · ")}
            </div>
          )}

          {view.review_reasons.length > 0 && (
            <div style={{ background: view.needs_review ? "var(--hazard-light)" : "var(--paper)", borderRadius: 6, padding: "10px 12px",
                          fontSize: 13.5, marginBottom: 14 }}>
              <b>{view.needs_review ? "Perlu ditinjau:" : "Sudah ditinjau:"}</b> {view.review_reasons.join(" · ")}
            </div>
          )}

          {/* the taps */}
          <div className="label" style={{ marginBottom: 6 }}>Catatan absen</div>
          {(detail?.events ?? []).length === 0 ? (
            <div style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 14 }}>Tidak ada absen hari ini.</div>
          ) : (
            detail!.events.map((e) => (
              <div key={e.id} style={{ display: "flex", gap: 12, padding: "10px 0", borderTop: "1px solid var(--line)" }}>
                {e.has_selfie ? <SelfieThumb eventId={e.id} /> : e.source_code === "fingerprint" ? (
                  <div title="Mesin sidik jari" style={{ width: 56, height: 56, borderRadius: 6, background: "var(--midnight-soft)",
                                color: "var(--midnight)", display: "flex", flexDirection: "column", alignItems: "center",
                                justifyContent: "center", gap: 2, fontSize: 9.5 }}>
                    <Fingerprint size={22} /> sidik jari
                  </div>
                ) : (
                  <div style={{ width: 56, height: 56, borderRadius: 6, background: "var(--paper-2)", fontSize: 10.5,
                                color: "var(--steel)", display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
                    tanpa selfie
                  </div>
                )}
                <div style={{ flex: 1, fontSize: 13.5 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <b>{e.kind_label}</b><span className="mono">{e.time}</span>
                  </div>
                  <div style={{ color: "var(--steel)" }}>
                    {e.site ?? "Lokasi tidak diketahui"}{e.distance_m != null ? ` · ${e.distance_m} m` : ""}
                    {e.accuracy_m != null ? ` · GPS ±${Math.round(e.accuracy_m)} m` : ""} · {e.source}
                  </div>
                  {e.latitude != null && e.longitude != null && (
                    <a href={`https://www.google.com/maps?q=${e.latitude},${e.longitude}`} target="_blank" rel="noreferrer"
                       style={{ color: "var(--rust)", fontSize: 12.5 }}>Lihat di peta <ExternalLink size={12} /></a>
                  )}
                  {e.flag_labels.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                      {e.flag_labels.map((f) => <span key={f} className="pill soon">{f}</span>)}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}

          {/* actions */}
          {!locked && (
            <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {view.day_id && <button className={mode === "approve" ? "btn-rust" : "btn-ghost"} onClick={() => setMode("approve")}
                                        style={{ padding: "7px 12px", fontSize: 13 }}><Check size={14} /> Setujui</button>}
                {view.day_id && <button className="btn-ghost" onClick={() => setMode("reject")}
                                        style={{ padding: "7px 12px", fontSize: 13, ...(mode === "reject" ? { background: "var(--ink)", color: "var(--paper)" } : {}) }}>
                  <X size={14} /> Tolak</button>}
                <button className="btn-ghost" onClick={() => setMode("fix")}
                        style={{ padding: "7px 12px", fontSize: 13, ...(mode === "fix" ? { background: "var(--ink)", color: "var(--paper)" } : {}) }}>
                  <Clock size={14} /> Ubah jam</button>
                {view.decision && (
                  <button className="btn-ghost" onClick={reset} disabled={busy} style={{ padding: "7px 12px", fontSize: 13 }}>
                    <RotateCcw size={14} /> Batalkan keputusan</button>
                )}
              </div>

              {mode === "approve" && (
                <div style={{ marginTop: 12 }}>
                  {view.late_minutes > 0 && (
                    <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 14, marginBottom: 10 }}>
                      <input type="checkbox" checked={waiveLate} onChange={(e) => setWaiveLate(e.target.checked)} />
                      Maafkan terlambat {view.late_minutes} menit (tidak dipotong)
                    </label>
                  )}
                  {view.overtime_proposed_minutes > 0 && (
                    <div style={{ marginBottom: 10 }}>
                      <label className="label">Lembur disetujui (menit), usulan {view.overtime_proposed_minutes}</label>
                      <input className="input" type="number" min={0} value={overtime} onChange={(e) => setOvertime(Number(e.target.value) || 0)} />
                    </div>
                  )}
                  <label className="label">Catatan (opsional)</label>
                  <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="mis. sudah konfirmasi mandor" />
                  <button className="btn-rust" onClick={approve} disabled={busy} style={{ width: "100%", justifyContent: "center", marginTop: 10 }}>
                    {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Check size={15} />} Setujui hari ini
                  </button>
                </div>
              )}

              {mode === "reject" && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 8 }}>
                    {view.leave ? `Tap diabaikan; hari ini kembali dihitung ${view.leave.toLowerCase()}.` : "Hari ini dihitung tidak hadir."}
                  </div>
                  <label className="label">Alasan (wajib)</label>
                  <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="mis. titip absen, bukan orangnya" />
                  <button className="btn-rust" onClick={reject} disabled={busy || !note.trim()} style={{ width: "100%", justifyContent: "center", marginTop: 10 }}>
                    {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <X size={15} />} Tolak hari ini
                  </button>
                </div>
              )}

              {mode === "fix" && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <div><label className="label">Jam masuk</label>
                      <input className="input" type="time" value={clockIn} onChange={(e) => setClockIn(e.target.value)} /></div>
                    <div><label className="label">Jam pulang</label>
                      <input className="input" type="time" value={clockOut} onChange={(e) => setClockOut(e.target.value)} /></div>
                  </div>
                  <label className="label" style={{ marginTop: 10 }}>Alasan (wajib)</label>
                  <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="mis. lupa absen pulang, dicek mandor" />
                  <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 6 }}>Jam dari HR menggantikan jam dari HP, dan hari ini otomatis disetujui. Tercatat di log.</div>
                  <button className="btn-rust" onClick={fix} disabled={busy || !note.trim() || (!clockIn && !clockOut)}
                          style={{ width: "100%", justifyContent: "center", marginTop: 10 }}>
                    {busy ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Clock size={15} />} Simpan jam
                  </button>
                </div>
              )}
              {error && <div style={{ color: "var(--danger)", fontSize: 13.5, marginTop: 10 }}>{error}</div>}
            </div>
          )}

          {/* audit log */}
          {detail && detail.audit.length > 0 && (
            <div style={{ marginTop: 18, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
              <div className="label" style={{ marginBottom: 6 }}>Riwayat perubahan</div>
              {detail.audit.map((a) => (
                <div key={a.id} style={{ fontSize: 13, padding: "6px 0" }}>
                  <div><b>{a.actor}</b> · <span style={{ color: "var(--steel)" }}>{dateTimeWIB(a.at)}</span></div>
                  <div>{a.summary}</div>
                  {a.note && <div style={{ color: "var(--steel)" }}>&ldquo;{a.note}&rdquo;</div>}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
