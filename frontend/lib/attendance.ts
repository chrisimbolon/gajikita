// =============================================================================
// === frontend/lib/attendance.ts ===
// Helpers for the worker's Absen page (G2a): distance to a site, the selfie
// squeeze, the offline queue, and WIB time formatting.
// =============================================================================
import type { ClockKind, ClockPayload, SiteView } from "@/lib/api/worker";

// ── distance (same formula as backend/apps/attendance/geofence.py) ──
const EARTH_RADIUS_M = 6371008.8;

export function haversineM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const rad = (d: number) => (d * Math.PI) / 180;
  const dp = rad(lat2 - lat1);
  const dl = rad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
}

export interface NearestSite {
  site:     SiteView;
  distance: number;
  inside:   boolean;
}

/** The nearest pinned site, for the "you are 40 m from Workshop" line. The server makes the real decision. */
export function nearestSite(sites: SiteView[], lat: number, lng: number): NearestSite | null {
  let best: NearestSite | null = null;
  for (const s of sites) {
    if (s.latitude === null || s.longitude === null || s.radius_m === null) continue;
    const distance = haversineM(lat, lng, s.latitude, s.longitude);
    if (!best || distance < best.distance) best = { site: s, distance, inside: distance <= s.radius_m };
  }
  return best;
}

// ── selfie: shrink to ~50 KB before upload ──
const SELFIE_MAX_SIDE = 640;
const SELFIE_QUALITY = 0.7;

export async function shrinkSelfie(file: File): Promise<Blob> {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error("Foto tidak bisa dibaca."));
      i.src = url;
    });
    const scale = Math.min(1, SELFIE_MAX_SIDE / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", SELFIE_QUALITY));
    return blob ?? file;
  } finally {
    URL.revokeObjectURL(url);
  }
}

// ── offline queue: taps kept on the phone until there is signal ──
// localStorage holds text only, so the selfie is kept as a data URL
// (~70 KB each; room for dozens of taps).
const QUEUE_KEY = "gajikita_pending_taps";

export interface PendingTap {
  client_id:  string;
  kind:       ClockKind;
  latitude:   number | null;
  longitude:  number | null;
  accuracy:   number | null;
  phone_time: string;
  selfie:     string | null;   // data URL
}

export function loadQueue(): PendingTap[] {
  try {
    const raw = typeof window === "undefined" ? null : localStorage.getItem(QUEUE_KEY);
    return raw ? (JSON.parse(raw) as PendingTap[]) : [];
  } catch {
    return [];
  }
}

function saveQueue(items: PendingTap[]) {
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(items));
  } catch {
    // Storage full: keep the tap without its photo rather than lose the tap.
    try {
      localStorage.setItem(QUEUE_KEY, JSON.stringify(items.map((t) => ({ ...t, selfie: null }))));
    } catch { /* nothing more we can do */ }
  }
}

export function enqueue(tap: PendingTap) {
  saveQueue([...loadQueue().filter((t) => t.client_id !== tap.client_id), tap]);
}

export function dequeue(clientId: string) {
  saveQueue(loadQueue().filter((t) => t.client_id !== clientId));
}

export function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

export async function dataUrlToBlob(dataUrl: string): Promise<Blob> {
  const res = await fetch(dataUrl);
  return res.blob();
}

export async function pendingToPayload(t: PendingTap): Promise<ClockPayload> {
  return {
    kind: t.kind, latitude: t.latitude, longitude: t.longitude, accuracy: t.accuracy,
    phone_time: t.phone_time, client_id: t.client_id, queued: true,
    selfie: t.selfie ? await dataUrlToBlob(t.selfie) : null,
  };
}

export function newClientId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  // Fallback for older browsers: RFC 4122 v4 from Math.random.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// ── time, always shown in WIB whatever the phone's own setting ──
const WIB = "Asia/Jakarta";

export function timeWIB(iso: string): string {
  return new Intl.DateTimeFormat("id-ID", { timeZone: WIB, hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function longDateWIB(d: Date = new Date()): string {
  return new Intl.DateTimeFormat("id-ID", { timeZone: WIB, weekday: "long", day: "numeric", month: "long", year: "numeric" })
    .format(d);
}
