"use client";
// =============================================================================
// SiteMap — a Leaflet + OpenStreetMap map for HR's Lokasi page (G2b).
// Shows one pin with its radius circle; a click on the map reports the spot
// through onPick so the page can move the draft pin there.
// Leaflet touches `window`, so it is loaded only in the browser (dynamic import).
// =============================================================================
import "leaflet/dist/leaflet.css";
import type { Circle, CircleMarker, Map as LeafletMap } from "leaflet";
import { useEffect, useRef, useState } from "react";

type LeafletModule = typeof import("leaflet");

const BATAM: [number, number] = [1.1301, 104.0529];
const PIN_COLOR = "#013D5A";   // Midnight

export interface MapPoint { lat: number; lng: number }

interface Props {
  pin:      MapPoint | null;
  radius:   number;
  focusKey: string;                       // change it (e.g. the selected site's id) to re-centre the map
  onPick:   (lat: number, lng: number) => void;
  height?:  number;
}

export default function SiteMap({ pin, radius, focusKey, onPick, height = 420 }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const L = useRef<LeafletModule | null>(null);
  const map = useRef<LeafletMap | null>(null);
  const circle = useRef<Circle | null>(null);
  const marker = useRef<CircleMarker | null>(null);
  const pick = useRef(onPick);
  const [ready, setReady] = useState(false);

  useEffect(() => { pick.current = onPick; }, [onPick]);

  // create the map once
  useEffect(() => {
    let cancelled = false;
    import("leaflet").then((mod) => {
      const lib = ((mod as unknown as { default?: LeafletModule }).default ?? mod) as LeafletModule;
      if (cancelled || !el.current || map.current) return;
      L.current = lib;
      const m = lib.map(el.current).setView(BATAM, 12);
      lib.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(m);
      m.on("click", (e) => pick.current(e.latlng.lat, e.latlng.lng));
      map.current = m;
      setReady(true);
    });
    return () => {
      cancelled = true;
      map.current?.remove();
      map.current = null;
      circle.current = null;
      marker.current = null;
    };
  }, []);

  // draw the pin and its radius
  useEffect(() => {
    const lib = L.current, m = map.current;
    if (!ready || !lib || !m) return;
    circle.current?.remove();
    marker.current?.remove();
    circle.current = null;
    marker.current = null;
    if (!pin) return;
    circle.current = lib.circle([pin.lat, pin.lng], { radius, color: PIN_COLOR, weight: 2, fillOpacity: 0.12 }).addTo(m);
    marker.current = lib.circleMarker([pin.lat, pin.lng], {
      radius: 7, color: "#fff", weight: 2, fillColor: PIN_COLOR, fillOpacity: 1,
    }).addTo(m);
  }, [ready, pin?.lat, pin?.lng, radius]);   // eslint-disable-line react-hooks/exhaustive-deps

  // re-centre when another site is chosen
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    if (pin) m.setView([pin.lat, pin.lng], radius > 600 ? 14 : 16);
    else m.setView(BATAM, 12);
  }, [ready, focusKey]);   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={el} style={{ height, width: "100%", borderRadius: 8, border: "1px solid var(--line)", zIndex: 0 }} />
  );
}
