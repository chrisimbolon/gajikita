"use client";
// =============================================================================
// /absen/cuti — leave on the worker's phone (G7, 28 Oct 2026).
//
//   ask for cuti tahunan / sakit / cuti khusus / izin tanpa upah (with a photo of the
//   doctor's letter if there is one), see my requests and cancel one still waiting.
//   A site manager (someone's "Mandor / atasan") also approves the crew's requests here.
// =============================================================================
import {
  Leave, LeaveInput, LeaveKind, LEAVE_STATUS_STYLE, MyLeave, periodText, shrinkPhoto, workerLeaveApi,
} from "@/lib/api/leave";
import { errorMessage } from "@/lib/api/worker";
import { tokenStorage } from "@/lib/auth";
import { todayISO } from "@/lib/format";
import { ArrowLeft, Check, Loader2, Paperclip, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

interface Notice { tone: "ok" | "error"; text: string }

const KIND_HINT: Record<LeaveKind, string> = {
  annual:  "Dibayar. Memotong sisa cuti tahunan.",
  sick:    "Dibayar. Lampirkan foto surat dokter jika ada.",
  special: "Dibayar. Menikah, keluarga meninggal, istri melahirkan…",
  unpaid:  "Tidak dibayar. Gaji hari itu dipotong.",
};

function StatusPill({ l }: { l: Leave }) {
  const s = LEAVE_STATUS_STYLE[l.status];
  return <span className="pill" style={{ background: s.bg, color: s.fg }}>{l.status_label}</span>;
}

function LeaveLine({ l }: { l: Leave }) {
  return (
    <>
      <div style={{ fontWeight: 700, fontSize: 14.5 }}>{l.label}</div>
      <div style={{ fontSize: 13.5, color: "var(--ink-soft)" }}>{periodText(l.start_date, l.end_date)} · {l.days} hari kerja</div>
      {l.reason && <div style={{ fontSize: 13, color: "var(--steel)", marginTop: 2 }}>{l.reason}</div>}
    </>
  );
}

function CrewCard({ l, onDone }: { l: Leave; onDone: (n: Notice) => void }) {
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const decide = async (action: "approve" | "reject") => {
    setBusy(true);
    try {
      await workerLeaveApi.decide(l.id, action, note);
      onDone({ tone: "ok", text: `${l.employee.full_name}: ${action === "approve" ? "disetujui" : "ditolak"}.` });
    } catch (err) {
      onDone({ tone: "error", text: errorMessage(err, "Keputusan gagal disimpan.") });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: "12px 0", borderTop: "1px solid var(--line)" }}>
      <div style={{ fontSize: 13, color: "var(--steel)", fontWeight: 600 }}>{l.employee.full_name}</div>
      <LeaveLine l={l} />
      {l.sick_note_missing && <div style={{ fontSize: 12.5, color: "var(--hazard-dark)", marginTop: 4 }}>Sakit lebih dari 2 hari tanpa surat dokter.</div>}
      {rejecting ? (
        <div style={{ marginTop: 10 }}>
          <textarea className="input" rows={2} value={note} onChange={(e) => setNote(e.target.value)}
                    placeholder="Alasan penolakan" style={{ width: "100%", fontSize: 15 }} />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
            <button className="btn-ghost" disabled={busy} onClick={() => setRejecting(false)} style={{ padding: "12px 0" }}>Batal</button>
            <button className="btn-rust" disabled={busy || !note.trim()} onClick={() => decide("reject")}
                    style={{ padding: "12px 0", justifyContent: "center", background: "var(--danger)" }}>Tolak</button>
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10 }}>
          <button className="btn-ghost" disabled={busy} onClick={() => setRejecting(true)}
                  style={{ padding: "12px 0", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
            <X size={16} /> Tolak
          </button>
          <button className="btn-rust" disabled={busy} onClick={() => decide("approve")}
                  style={{ padding: "12px 0", justifyContent: "center" }}>
            {busy ? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> : <Check size={16} />} Setujui
          </button>
        </div>
      )}
    </div>
  );
}

export default function CutiPage() {
  const [data, setData] = useState<MyLeave | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [kind, setKind] = useState<LeaveKind>("annual");
  const [special, setSpecial] = useState("");
  const [start, setStart] = useState(todayISO());
  const [end, setEnd] = useState(todayISO());
  const [reason, setReason] = useState("");
  const [photo, setPhoto] = useState<{ blob: Blob; name: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setData(await workerLeaveApi.mine()); }
    catch (err) { setNotice({ tone: "error", text: errorMessage(err, "Data cuti tidak bisa dimuat. Periksa sinyal.") }); }
  }, []);

  useEffect(() => {
    if (!tokenStorage.getAccess()) { window.location.href = "/absen/masuk"; return; }
    load();
  }, [load]);

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try { setPhoto(await shrinkPhoto(file)); }
    catch { setNotice({ tone: "error", text: "Foto tidak bisa dibaca. Ambil foto lagi (format JPG/PNG) atau pilih PDF." }); }
  };

  const submit = async () => {
    setBusy(true);
    setNotice(null);
    const body: LeaveInput = { kind, special_reason: special, start_date: start, end_date: end < start ? start : end,
                               reason, attachment: photo };
    try {
      const res = await workerLeaveApi.ask(body);
      setNotice({ tone: "ok", text: res.message });
      setReason(""); setPhoto(null);
      await load();
    } catch (err) {
      setNotice({ tone: "error", text: errorMessage(err, "Pengajuan gagal dikirim. Periksa sinyal lalu coba lagi.") });
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (l: Leave) => {
    if (!window.confirm(`Batalkan ${l.label.toLowerCase()} ${periodText(l.start_date, l.end_date)}?`)) return;
    try { await workerLeaveApi.cancel(l.id); setNotice({ tone: "ok", text: "Pengajuan dibatalkan." }); await load(); }
    catch (err) { setNotice({ tone: "error", text: errorMessage(err, "Gagal membatalkan.") }); }
  };

  const afterDecision = async (n: Notice) => { setNotice(n); await load(); };

  if (!data) {
    return (
      <div style={{ paddingTop: 80, textAlign: "center", color: "var(--steel)" }}>
        {notice ? notice.text : <Loader2 size={22} style={{ animation: "spin 1s linear infinite" }} />}
        <div style={{ marginTop: 16 }}><Link href="/absen">Kembali ke absen</Link></div>
      </div>
    );
  }

  const a = data.annual;
  const kindOptions = data.kinds;

  return (
    <div>
      <div style={{ background: "var(--midnight)", color: "#FFFFFF", borderRadius: 20, padding: "16px 20px 18px", marginBottom: 14 }}>
        <Link href="/absen" style={{ color: "#FFFFFF", fontSize: 13.5, fontWeight: 600, textDecoration: "none",
                                     display: "inline-flex", alignItems: "center", gap: 6 }}>
          <ArrowLeft size={16} /> Absen
        </Link>
        <div style={{ fontSize: 23, fontWeight: 800, marginTop: 10 }}>Cuti & izin</div>
        <div style={{ fontSize: 13.5, color: "var(--on-dark-muted)" }}>{data.employee.full_name}</div>
        <div style={{ marginTop: 12, background: "rgba(255,255,255,0.10)", borderRadius: 10, padding: "10px 12px", fontSize: 14 }}>
          {a.entitled > 0 ? (
            <>Sisa cuti tahunan {a.year}: <b style={{ color: "var(--marigold)", fontSize: 17 }}>{a.left}</b> dari {a.entitled} hari</>
          ) : (
            <>Cuti tahunan mulai {periodText(a.from_date, a.from_date)} (setelah 12 bulan bekerja)</>
          )}
        </div>
      </div>

      {notice && (
        <div style={{ background: notice.tone === "ok" ? "var(--workshop-lt)" : "var(--danger-light)",
                      color: notice.tone === "ok" ? "var(--workshop)" : "var(--danger)",
                      padding: "12px 14px", borderRadius: 6, fontSize: 14, fontWeight: 600, marginBottom: 14 }}>{notice.text}</div>
      )}

      {/* site manager: the crew's requests */}
      {data.is_approver && (
        <div className="card" style={{ padding: 16, marginBottom: 14, borderColor: data.to_approve.length ? "var(--marigold)" : undefined }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {data.to_approve.length > 0 && (
              <span style={{ background: "var(--marigold)", color: "var(--midnight)", borderRadius: 999, minWidth: 24, height: 24,
                             display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 13 }}>
                {data.to_approve.length}
              </span>
            )}
            <div className="label" style={{ margin: 0 }}>Menunggu persetujuan Anda</div>
          </div>
          {data.to_approve.length === 0 ? (
            <div style={{ fontSize: 14, color: "var(--steel)", marginTop: 8 }}>Tidak ada pengajuan dari tim Anda.</div>
          ) : (
            data.to_approve.map((l) => <CrewCard key={l.id} l={l} onDone={afterDecision} />)
          )}
          {data.crew_recent.length > 0 && (
            <details style={{ marginTop: 10, fontSize: 13.5 }}>
              <summary style={{ cursor: "pointer", color: "var(--steel)" }}>Sudah diputuskan ({data.crew_recent.length})</summary>
              {data.crew_recent.map((l) => (
                <div key={l.id} style={{ padding: "8px 0", borderTop: "1px solid var(--line)", display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <div><b>{l.employee.full_name}</b> · {l.label}<div style={{ color: "var(--steel)" }}>{periodText(l.start_date, l.end_date)}</div></div>
                  <StatusPill l={l} />
                </div>
              ))}
            </details>
          )}
        </div>
      )}

      {/* ask */}
      <div className="card" style={{ padding: 16, marginBottom: 14 }}>
        <div className="label" style={{ marginBottom: 10 }}>Ajukan cuti / izin</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {kindOptions.map((k) => {
            const on = kind === k.value;
            return (
              <button key={k.value} onClick={() => setKind(k.value)} style={{
                padding: "12px 10px", borderRadius: 12, fontSize: 14.5, fontWeight: 700, textAlign: "left",
                border: on ? "2px solid var(--midnight)" : "1px solid var(--line)",
                background: on ? "var(--midnight-soft)" : "#FFFFFF", color: "var(--midnight)",
              }}>{k.label}</button>
            );
          })}
        </div>
        <div style={{ fontSize: 13, color: "var(--steel)", margin: "8px 0 12px" }}>{KIND_HINT[kind]}</div>

        {kind === "special" && (
          <label style={{ display: "block", marginBottom: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Alasan</div>
            <select className="input" value={special} onChange={(e) => setSpecial(e.target.value)} style={{ width: "100%", fontSize: 15 }}>
              <option value="">Pilih…</option>
              {data.special_reasons.map((r) => <option key={r.value} value={r.value}>{r.label} ({r.days} hari)</option>)}
            </select>
          </label>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
          <label>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Mulai</div>
            <input className="input" type="date" value={start} style={{ width: "100%", fontSize: 15 }}
                   onChange={(e) => { setStart(e.target.value); if (e.target.value > end) setEnd(e.target.value); }} />
          </label>
          <label>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Sampai</div>
            <input className="input" type="date" value={end} min={start} style={{ width: "100%", fontSize: 15 }}
                   onChange={(e) => setEnd(e.target.value)} />
          </label>
        </div>

        <label style={{ display: "block", marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Keterangan</div>
          <textarea className="input" rows={2} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)}
                    placeholder={kind === "sick" ? "Contoh: demam, istirahat 2 hari" : "Contoh: pulang kampung"}
                    style={{ width: "100%", fontSize: 15 }} />
        </label>

        {(kind === "sick" || kind === "special") && (
          <label className="btn-ghost" style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, padding: "12px 0",
                                               marginBottom: 12, cursor: "pointer" }}>
            <Paperclip size={16} /> {photo ? "Ganti lampiran" : kind === "sick" ? "Foto surat dokter" : "Lampiran (jika ada)"}
            <input type="file" accept="image/*,application/pdf" onChange={onFile} style={{ display: "none" }} />
          </label>
        )}
        {photo && (
          <div style={{ fontSize: 13, color: "var(--workshop)", marginTop: -6, marginBottom: 12 }}>
            Lampiran siap ({Math.max(1, Math.round(photo.blob.size / 1024))} KB){" "}
            <button onClick={() => setPhoto(null)} style={{ background: "none", border: "none", color: "var(--danger)", fontSize: 13 }}>hapus</button>
          </div>
        )}

        <button className="btn-marigold" disabled={busy || (kind === "special" && !special)} onClick={submit}
                style={{ width: "100%", justifyContent: "center", padding: "16px 0", fontSize: 17, borderRadius: 14 }}>
          {busy ? <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> : null} Kirim pengajuan
        </button>
        <div style={{ fontSize: 12.5, color: "var(--steel)", textAlign: "center", marginTop: 8 }}>
          Dihitung hari kerja shift Anda. Disetujui oleh {data.approver ?? "HR"}.
        </div>
      </div>

      {/* mine */}
      <div className="card" style={{ padding: 16 }}>
        <div className="label" style={{ marginBottom: 6 }}>Pengajuan saya</div>
        {data.requests.length === 0 ? (
          <div style={{ fontSize: 14, color: "var(--steel)" }}>Belum ada.</div>
        ) : (
          data.requests.map((l) => (
            <div key={l.id} style={{ padding: "12px 0", borderTop: "1px solid var(--line)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
                <div><LeaveLine l={l} /></div>
                <StatusPill l={l} />
              </div>
              {l.status === "pending" && (
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 6 }}>
                  <span style={{ fontSize: 12.5, color: "var(--steel)" }}>Menunggu {l.approver ?? "HR"}</span>
                  <button className="btn-ghost" onClick={() => cancel(l)} style={{ padding: "6px 12px", fontSize: 13 }}>Batalkan</button>
                </div>
              )}
              {l.status === "rejected" && l.decision_note && (
                <div style={{ fontSize: 13, color: "var(--danger)", marginTop: 4 }}>Ditolak {l.decided_by ?? ""}: {l.decision_note}</div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
