// =============================================================================
// === frontend/lib/api/worker.ts ===
// The worker's side: phone + PIN login and attendance taps (G2a, 27 Oct 2026).
// Mirrors backend/apps/employees/views.py and backend/apps/attendance/views.py.
// =============================================================================
import api from "@/lib/api";
import { tokenStorage } from "@/lib/auth";

export type ClockKind = "in" | "switch" | "out";

export interface ClockEventView {
  id:          string;
  kind:        ClockKind;
  kind_label:  string;
  date:        string;
  occurred_at: string;
  site:        { id: string; name: string } | null;
  distance_m:  number | null;
  accuracy_m:  number | null;
  flags:       string[];
  flag_labels: string[];
  has_selfie:  boolean;
}

export interface SiteView {
  id:         string;
  name:       string;
  kind:       "fixed" | "moving" | "vessel" | "none";
  kind_label: string;
  latitude:   number | null;
  longitude:  number | null;
  radius_m:   number | null;
}

export interface TodayView {
  must_change_pin: boolean;
  employee:   { id: string; employee_no: string; full_name: string };
  shift:      { name: string; start: string; end: string } | null;
  sites:      SiteView[];
  clocked_in: boolean;
  date:       string;
  events:     ClockEventView[];
}

export interface ClockPayload {
  kind:       ClockKind;
  latitude:   number | null;
  longitude:  number | null;
  accuracy:   number | null;
  phone_time: string;          // ISO timestamp of the tap, from the phone
  client_id:  string;          // same id on every retry, so a retry never duplicates
  queued:     boolean;         // true when it was stored on the phone without signal
  selfie:     Blob | null;
}

export interface ClockResult {
  event:   ClockEventView;
  message: string;
}

export const workerApi = {
  async login(phone: string, pin: string): Promise<{ must_change_pin: boolean }> {
    const { data } = await api.post("/api/worker/login/", { phone, pin });
    tokenStorage.set(data.access, data.refresh);
    return { must_change_pin: data.must_change_pin };
  },

  async changePin(current_pin: string, new_pin: string): Promise<void> {
    await api.post("/api/worker/pin/", { current_pin, new_pin });
  },

  async today(): Promise<TodayView> {
    const { data } = await api.get("/api/attendance/today/");
    return data;
  },

  async clock(p: ClockPayload): Promise<ClockResult> {
    const form = new FormData();
    form.append("kind", p.kind);
    if (p.latitude !== null && p.longitude !== null) {
      form.append("latitude", String(p.latitude));
      form.append("longitude", String(p.longitude));
    }
    if (p.accuracy !== null) form.append("accuracy", String(Math.round(p.accuracy * 10) / 10));
    form.append("phone_time", p.phone_time);
    form.append("client_id", p.client_id);
    form.append("queued", p.queued ? "true" : "false");
    if (p.selfie) form.append("selfie", p.selfie, "selfie.jpg");
    const { data } = await api.post("/api/attendance/clock/", form, { timeout: 20000 });
    return { event: data.event, message: data.message };
  },

  logout() {
    tokenStorage.clear();
  },
};

/** The server's message for a failed request, or a plain fallback. */
export function errorMessage(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { message?: string; detail?: string } } };
  return e?.response?.data?.message || e?.response?.data?.detail || fallback;
}

/** True when the request never reached the server (no signal, server down). */
export function isNetworkError(err: unknown): boolean {
  const e = err as { response?: unknown; code?: string };
  return !e?.response;
}
