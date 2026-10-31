"use client";
// =============================================================================
// /absen — the worker's clock-in page (G2a, 27 Oct 2026).
//
//   tap Masuk / Pindah lokasi / Pulang -> front camera -> selfie squeezed to
//   ~50 KB -> sent with GPS + accuracy + the phone's time. No signal? The tap
//   is kept on the phone and sent automatically later (same client_id, so a
//   retry never makes a duplicate). The server decides site and flags; this
//   page only shows them.
// =============================================================================
import Wordmark from "@/components/Wordmark";
import {
  ClockKind, ClockResult, TodayView, errorMessage, isNetworkError, workerApi,
} from "@/lib/api/worker";
import {
  PendingTap, blobToDataUrl, dequeue, enqueue, loadQueue, longDateWIB, nearestSite, newClientId,
  pendingToPayload, shrinkSelfie, timeWIB,
} from "@/lib/attendance";
import { tokenStorage } from "@/lib/auth";
import { workerLeaveApi } from "@/lib/api/leave";
import { CalendarOff, ChevronRight, CloudOff, Loader2, LogIn, LogOut, MapPin, Navigation, Repeat } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

const TODAY_CACHE_KEY = "gajikita_today_cache";
const KIND_LABEL: Record<ClockKind, string> = { in: "Masuk", switch: "Pindah lokasi", out: "Pulang" };

interface Gps { lat: number; lng: number; accuracy: number }
interface Notice { tone: "ok" | "warn" | "error"; text: string }

const NOTICE_COLORS: Record<Notice["tone"], { bg: string; fg: string }> = {
  ok:    { bg: "var(--workshop-lt)", fg: "var(--workshop)" },
  warn:  { bg: "var(--hazard-light)", fg: "var(--hazard-dark)" },
  error: { bg: "var(--danger-light)", fg: "var(--danger)" },
};

function readCache(): TodayView | null {
  try {
    const raw = localStorage.getItem(TODAY_CACHE_KEY);
    return raw ? (JSON.parse(raw) as TodayView) : null;
  } catch {
    return null;
  }
}

export default function AbsenPage() {
  const [today, setToday] = useState<TodayView | null>(null);
  const [offline, setOffline] = useState(false);
  const [gps, setGps] = useState<Gps | null>(null);
  const [gpsProblem, setGpsProblem] = useState<string | null>("Mencari sinyal GPS…");
  const [pending, setPending] = useState<PendingTap[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const kindRef = useRef<ClockKind>("in");
  const flushing = useRef(false);
  const [leaveWaiting, setLeaveWaiting] = useState(0);     // site manager: crew leave requests waiting (G7)

  useEffect(() => {
    if (!tokenStorage.getAccess()) return;
    workerLeaveApi.mine().then((m) => setLeaveWaiting(m.to_approve.length)).catch(() => { /* no signal: no badge */ });
  }, []);

  // ── today's state from the server (or the last copy when there's no signal) ──
  const refresh = useCallback(async () => {
    try {
      const data = await workerApi.today();
      if (data.must_change_pin) { window.location.href = "/absen/pin"; return; }
      setToday(data);
      setOffline(false);
      try { localStorage.setItem(TODAY_CACHE_KEY, JSON.stringify(data)); } catch { /* ignore */ }
    } catch (err) {
      if (isNetworkError(err)) {
        setOffline(true);
        setToday((cur) => cur ?? readCache());
      } else {
        setNotice({ tone: "error", text: errorMessage(err, "Data absen tidak bisa dimuat.") });
      }
    }
  }, []);

  // ── send taps that were kept on the phone ──
  const flush = useCallback(async () => {
    if (flushing.current) return;
    flushing.current = true;
    try {
      let sent = 0;
      for (const tap of loadQueue()) {
        try {
          await workerApi.clock(await pendingToPayload(tap));
          dequeue(tap.client_id);
          sent += 1;
        } catch (err) {
          if (isNetworkError(err)) break;            // still no signal: try again later
          dequeue(tap.client_id);                     // refused by the server: don't retry forever
          setNotice({ tone: "error", text: errorMessage(err, "Satu absen yang tersimpan ditolak server.") });
        }
      }
      setPending(loadQueue());
      if (sent > 0) {
        setNotice({ tone: "ok", text: `${sent} absen yang tersimpan sudah terkirim.` });
        await refresh();
      }
    } finally {
      flushing.current = false;
    }
  }, [refresh]);

  useEffect(() => {
    if (!tokenStorage.getAccess()) { window.location.href = "/absen/masuk"; return; }
    setPending(loadQueue());
    refresh().then(flush);
    const onOnline = () => { flush(); };
    window.addEventListener("online", onOnline);
    const timer = window.setInterval(() => { if (loadQueue().length) flush(); }, 30000);
    return () => { window.removeEventListener("online", onOnline); window.clearInterval(timer); };
  }, [refresh, flush]);

  // ── live GPS while the page is open ──
  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setGpsProblem("HP ini tidak bisa membaca lokasi di halaman ini (perlu https).");
      return;
    }
    const id = navigator.geolocation.watchPosition(
      (pos) => {
        setGps({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy });
        setGpsProblem(null);
      },
      (err) => {
        setGpsProblem(err.code === err.PERMISSION_DENIED
          ? "Izin lokasi ditolak. Aktifkan izin lokasi untuk browser ini, lalu muat ulang halaman."
          : "Mencari sinyal GPS… Coba di tempat terbuka.");
      },
      { enableHighAccuracy: true, maximumAge: 10000, timeout: 20000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, []);

  // ── a tap ──
  const startTap = (kind: ClockKind) => {
    kindRef.current = kind;
    setNotice(null);
    fileRef.current?.click();
  };

  const onPhoto = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";                               // allow the same photo flow again
    if (!file) return;
    setBusy(true);
    const kind = kindRef.current;
    const tap: PendingTap = {
      client_id: newClientId(), kind,
      latitude: gps?.lat ?? null, longitude: gps?.lng ?? null, accuracy: gps?.accuracy ?? null,
      phone_time: new Date().toISOString(), selfie: null,
    };
    let selfie: Blob;
    try {
      selfie = await shrinkSelfie(file);
    } catch {
      // A photo the browser can't read (e.g. HEIC on a Mac) is NOT "no signal": say so, queue nothing.
      setNotice({ tone: "error", text: "Foto tidak bisa dibaca. Ambil foto lagi (format JPG/PNG)." });
      setBusy(false);
      return;
    }
    try {
      const res: ClockResult = await workerApi.clock({ ...tap, queued: false, selfie });
      const review = res.event.flags.length > 0;
      setNotice({ tone: review ? "warn" : "ok", text: res.message });
      await refresh();
    } catch (err) {
      if (isNetworkError(err)) {
        enqueue({ ...tap, selfie: selfie ? await blobToDataUrl(selfie) : null });
        setPending(loadQueue());
        setNotice({ tone: "warn", text: `Tidak ada sinyal. ${KIND_LABEL[kind]} disimpan di HP dan dikirim otomatis saat ada sinyal.` });
      } else {
        setNotice({ tone: "error", text: errorMessage(err, "Absen gagal. Coba lagi.") });
      }
    } finally {
      setBusy(false);
    }
  };

  const logout = () => {
    if (pending.length && !window.confirm("Masih ada absen yang belum terkirim. Tetap keluar?")) return;
    workerApi.logout();
    window.location.href = "/absen/masuk";
  };

  // ── what to show ──
  if (!today) {
    return (
      <div style={{ paddingTop: 80, textAlign: "center", color: "var(--steel)" }}>
        {offline ? "Tidak ada sinyal. Buka lagi saat ada sinyal." : <Loader2 size={22} style={{ animation: "spin 1s linear infinite" }} />}
      </div>
    );
  }

  const lastPending = pending.length ? pending[pending.length - 1] : null;
  const clockedIn = lastPending ? lastPending.kind !== "out" : today.clocked_in;
  const lastServer = today.events.length ? today.events[today.events.length - 1] : null;
  const near = gps ? nearestSite(today.sites, gps.lat, gps.lng) : null;
  const unfencedOnly = today.sites.length > 0 && today.sites.every((s) => s.kind === "vessel" || s.kind === "none");

  let status: string;
  if (lastPending) status = `${KIND_LABEL[lastPending.kind]} ${timeWIB(lastPending.phone_time)} (menunggu sinyal)`;
  else if (lastServer) status = `${lastServer.kind_label} ${timeWIB(lastServer.occurred_at)}${lastServer.site ? ` di ${lastServer.site.name}` : ""}`;
  else status = "Belum absen hari ini";

  return (
    <div>
      {/* header: Midnight, as in the "Arah A" design */}
      <div style={{ background: "var(--midnight)", color: "#FFFFFF", borderRadius: 20, padding: "18px 20px 20px", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Wordmark size={20} onDark />
          <button onClick={logout} aria-label="Keluar"
                  style={{ background: "rgba(255,255,255,0.12)", border: "none", color: "#FFFFFF", borderRadius: 10,
                           padding: "7px 12px", fontSize: 13, fontWeight: 600 }}>
            <LogOut size={14} style={{ verticalAlign: "-2px" }} /> Keluar
          </button>
        </div>
        <div style={{ fontSize: 13, color: "var(--on-dark-muted)", marginTop: 16 }}>{longDateWIB()}</div>
        <div style={{ fontSize: 23, fontWeight: 800, letterSpacing: "-0.01em", marginTop: 2 }}>{today.employee.full_name}</div>
        <div className="mono" style={{ fontSize: 13, color: "var(--on-dark-muted)" }}>
          {today.employee.employee_no}{today.shift ? ` · Shift ${today.shift.name} ${today.shift.start}–${today.shift.end}` : ""}
        </div>
        <div style={{ marginTop: 14, fontSize: 14.5, fontWeight: 700, background: "rgba(255,255,255,0.10)", borderRadius: 10, padding: "9px 12px" }}>
          {status}
        </div>
        {offline && (
          <div style={{ marginTop: 8, fontSize: 13, color: "var(--marigold)" }}>
            <CloudOff size={14} style={{ verticalAlign: "-2px" }} /> Tidak ada sinyal, menampilkan data terakhir.
          </div>
        )}
      </div>

      {/* GPS */}
      <div className="card" style={{ padding: 16, marginBottom: 14, display: "flex", gap: 12, alignItems: "flex-start" }}>
        <Navigation size={18} style={{ marginTop: 2, color: gps ? "var(--workshop)" : "var(--steel)" }} />
        <div style={{ fontSize: 14, lineHeight: 1.5 }}>
          {gps ? (
            <>
              <div>GPS akurat ±{Math.round(gps.accuracy)} m{gps.accuracy > 100 ? " (kurang akurat, coba di tempat terbuka)" : ""}</div>
              {near && (
                <div style={{ color: near.inside ? "var(--workshop)" : "var(--hazard-dark)", fontWeight: 600 }}>
                  <MapPin size={14} style={{ verticalAlign: "-2px" }} />{" "}
                  {near.inside ? "Di dalam area" : "Di luar area"} {near.site.name}
                  {" "}({Math.round(near.distance)} m dari titik, radius {near.site.radius_m} m)
                </div>
              )}
              {!near && unfencedOnly && <div style={{ color: "var(--steel)" }}>Lokasi kerja Anda tanpa batas area.</div>}
            </>
          ) : (
            <div style={{ color: "var(--steel)" }}>{gpsProblem}</div>
          )}
        </div>
      </div>

      {/* the buttons */}
      <input ref={fileRef} type="file" accept="image/*" capture="user" onChange={onPhoto} style={{ display: "none" }} />
      {!clockedIn ? (
        <button className="btn-marigold" disabled={busy} onClick={() => startTap("in")}
                style={{ width: "100%", justifyContent: "center", padding: "28px 0", fontSize: 23, borderRadius: 20, marginBottom: 10 }}>
          {busy ? <Loader2 size={22} style={{ animation: "spin 1s linear infinite" }} /> : <LogIn size={22} />} MASUK
        </button>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
          <button className="btn-ghost" disabled={busy} onClick={() => startTap("switch")}
                  style={{ padding: "20px 0", fontSize: 15, display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
            <Repeat size={18} /> PINDAH LOKASI
          </button>
          <button className="btn-rust" disabled={busy} onClick={() => startTap("out")}
                  style={{ padding: "20px 0", fontSize: 17, justifyContent: "center" }}>
            {busy ? <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} /> : <LogOut size={20} />} PULANG
          </button>
        </div>
      )}
      <p style={{ fontSize: 12.5, color: "var(--steel)", textAlign: "center", margin: "0 0 14px" }}>
        Setelah menekan tombol, kamera depan terbuka untuk selfie.
      </p>

      {/* cuti / izin (G7) */}
      <Link href="/absen/cuti" className="card" style={{ padding: "14px 16px", marginBottom: 14, display: "flex", alignItems: "center",
                                                    gap: 12, textDecoration: "none", color: "var(--ink)" }}>
        <CalendarOff size={20} style={{ color: "var(--midnight)" }} />
        <div style={{ flexGrow: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>Cuti & izin</div>
          <div style={{ fontSize: 13, color: "var(--steel)" }}>Ajukan cuti, sakit atau izin</div>
        </div>
        {leaveWaiting > 0 && (
          <span style={{ background: "var(--marigold)", color: "var(--midnight)", borderRadius: 999, padding: "2px 10px",
                         fontWeight: 800, fontSize: 13 }}>{leaveWaiting} perlu disetujui</span>
        )}
        <ChevronRight size={18} style={{ color: "var(--steel)" }} />
      </Link>

      {notice && (
        <div style={{ background: NOTICE_COLORS[notice.tone].bg, color: NOTICE_COLORS[notice.tone].fg, padding: "12px 14px",
                      borderRadius: 6, fontSize: 14, fontWeight: 600, marginBottom: 14 }}>{notice.text}</div>
      )}

      {pending.length > 0 && (
        <div className="card" style={{ padding: 16, marginBottom: 14, borderColor: "var(--hazard)" }}>
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>
            <CloudOff size={15} style={{ verticalAlign: "-2px" }} /> {pending.length} absen menunggu sinyal
          </div>
          {pending.map((t) => (
            <div key={t.client_id} style={{ fontSize: 13.5, color: "var(--ink-soft)" }}>
              {KIND_LABEL[t.kind]} · {timeWIB(t.phone_time)}
            </div>
          ))}
          <button className="btn-ghost" onClick={() => flush()} style={{ marginTop: 10, padding: "6px 12px", fontSize: 13 }}>
            Kirim sekarang
          </button>
        </div>
      )}

      {/* today's taps */}
      <div className="card" style={{ padding: 16 }}>
        <div className="label" style={{ marginBottom: 10 }}>Absen hari ini</div>
        {today.events.length === 0 ? (
          <div style={{ fontSize: 14, color: "var(--steel)" }}>Belum ada.</div>
        ) : (
          today.events.map((ev) => (
            <div key={ev.id} style={{ padding: "10px 0", borderTop: "1px solid var(--line)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14.5 }}>
                <span style={{ fontWeight: 600 }}>{ev.kind_label}</span>
                <span className="mono">{timeWIB(ev.occurred_at)}</span>
              </div>
              <div style={{ fontSize: 13, color: "var(--steel)" }}>
                {ev.site ? ev.site.name : "Lokasi tidak diketahui"}
                {ev.distance_m !== null ? ` · ${ev.distance_m} m` : ""}
                {ev.accuracy_m !== null ? ` · GPS ±${Math.round(ev.accuracy_m)} m` : ""}
              </div>
              {ev.flag_labels.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                  {ev.flag_labels.map((f) => <span key={f} className="pill soon">{f}</span>)}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
