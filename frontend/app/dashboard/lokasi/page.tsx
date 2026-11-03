"use client";
// =============================================================================
// /dashboard/lokasi — HR's Sites page with a map (G2b, 27 Oct 2026).
// Pick a site on the left; on the right click the map (or use "Lokasi saya")
// to place the pin, set the radius, save. Moving a pin keeps the old one in
// the history, so past attendance is still measured against the old spot.
// =============================================================================
import SiteMap, { MapPoint } from "@/components/SiteMap";
import { SITE_KIND_LABEL, Site, SiteKind, hrApi, readErrors } from "@/lib/api/hr";
import { dateTimeWIB } from "@/lib/format";
import { Crosshair, Loader2, MapPin, Plus, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

const RADIUS_PRESETS = [100, 150, 300, 500];
const KIND_HELP: Record<SiteKind, string> = {
  fixed: "Kantor, workshop, proyek gedung: dicek jaraknya dari titik.",
  moving: "Proyek jalan atau pipa: dicek jaraknya; pindahkan titik saat pekerjaan bergeser.",
  vessel: "Kapal: tidak dicek jaraknya; posisi dan selfie tetap dicatat.",
  none: "Sopir, surveyor: tidak dicek jaraknya; posisi tetap dicatat.",
};

export default function LokasiPage() {
  const [sites, setSites] = useState<Site[]>([]);
  const [selected, setSelected] = useState<Site | null>(null);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState<SiteKind>("fixed");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const load = useCallback(async (selectId?: string) => {
    try {
      const list = await hrApi.sites();
      setSites(list);
      setPageError(null);
      const id = selectId ?? list[0]?.id;
      if (id) setSelected(await hrApi.site(id));
    } catch (err) {
      setPageError(readErrors(err).summary);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const choose = async (id: string) => {
    try { setSelected(await hrApi.site(id)); } catch (err) { setPageError(readErrors(err).summary); }
  };

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setAdding(true); setAddError(null);
    try {
      const site = await hrApi.createSite({ name: newName, kind: newKind });
      setNewName("");
      await load(site.id);
    } catch (err) {
      const r = readErrors(err);
      setAddError(r.fields.name ?? r.summary);
    } finally {
      setAdding(false);
    }
  };

  const onChanged = (site: Site) => {
    setSelected(site);
    setSites((cur) => cur.map((s) => (s.id === site.id ? { ...s, ...site } : s)));
  };

  return (
    <div>
      <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Lokasi Kerja</h1>
      <p style={{ color: "var(--steel)", marginTop: 0, marginBottom: 18, fontSize: 14 }}>
        Tempat karyawan absen. Absen di luar radius tetap tercatat, tapi ditandai untuk ditinjau HR.
      </p>
      {pageError && <div className="card" style={{ color: "var(--danger)", marginBottom: 16 }}>{pageError}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "280px minmax(0, 1fr)", gap: 18, alignItems: "start" }}>
        {/* site list + add */}
        <div>
          <form onSubmit={add} className="card" style={{ padding: 14, marginBottom: 12 }}>
            <label className="label">Lokasi baru</label>
            <input className="input" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="mis. Proyek Jalan Lintas Barat" required />
            <select className="input" value={newKind} onChange={(e) => setNewKind(e.target.value as SiteKind)} style={{ marginTop: 8 }}>
              {(Object.keys(SITE_KIND_LABEL) as SiteKind[]).map((k) => <option key={k} value={k}>{SITE_KIND_LABEL[k]}</option>)}
            </select>
            {addError && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 6 }}>{addError}</div>}
            <button className="btn-rust" disabled={adding || !newName.trim()} style={{ width: "100%", justifyContent: "center", marginTop: 10, padding: "8px 0" }}>
              {adding ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={15} />} Tambah
            </button>
          </form>

          {loading ? (
            <div style={{ color: "var(--steel)", padding: 10 }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
          ) : sites.length === 0 ? (
            <div style={{ color: "var(--steel)", fontSize: 13.5, padding: 6 }}>Belum ada lokasi.</div>
          ) : (
            sites.map((s) => (
              <button key={s.id} onClick={() => choose(s.id)} className="card"
                      style={{ display: "block", width: "100%", textAlign: "left", padding: 12, marginBottom: 8,
                               borderColor: selected?.id === s.id ? "var(--rust)" : undefined, opacity: s.is_active ? 1 : 0.55 }}>
                <div style={{ fontWeight: 700, fontSize: 14 }}>{s.name}</div>
                <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 2 }}>
                  {SITE_KIND_LABEL[s.kind]}
                  {s.location ? ` · radius ${s.location.radius_m} m` : s.kind === "fixed" || s.kind === "moving" ? " · belum ada titik" : ""}
                  {s.employee_count ? ` · ${s.employee_count} karyawan` : ""}
                  {!s.is_active ? " · nonaktif" : ""}
                </div>
              </button>
            ))
          )}
        </div>

        {/* the selected site */}
        {selected ? <SiteEditor key={selected.id} site={selected} onChanged={onChanged} /> : (
          <div className="card" style={{ color: "var(--steel)" }}>Tambahkan lokasi pertama di sebelah kiri.</div>
        )}
      </div>
    </div>
  );
}

function SiteEditor({ site, onChanged }: { site: Site; onChanged: (s: Site) => void }) {
  const [draft, setDraft] = useState<MapPoint | null>(site.location ? { lat: site.location.latitude, lng: site.location.longitude } : null);
  const [radius, setRadius] = useState<number>(site.location?.radius_m ?? 150);
  const [name, setName] = useState(site.name);
  const [kind, setKind] = useState<SiteKind>(site.kind);
  const [code, setCode] = useState(site.project_code);
  const [busy, setBusy] = useState<"pin" | "info" | "gps" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const pinChanged = !site.location || !draft || draft.lat !== site.location.latitude
    || draft.lng !== site.location.longitude || radius !== site.location.radius_m;
  const infoChanged = name !== site.name || kind !== site.kind || code !== site.project_code;

  const savePin = async () => {
    if (!draft) return;
    setBusy("pin"); setMsg(null);
    try {
      onChanged(await hrApi.movePin(site.id, round6(draft.lat), round6(draft.lng), radius));
      setMsg({ ok: true, text: site.location ? "Titik dipindah. Titik lama disimpan di riwayat." : "Titik disimpan." });
    } catch (err) {
      setMsg({ ok: false, text: readErrors(err).summary });
    } finally {
      setBusy(null);
    }
  };

  const saveInfo = async (patch: Partial<Pick<Site, "name" | "kind" | "project_code" | "is_active">>) => {
    setBusy("info"); setMsg(null);
    try {
      onChanged(await hrApi.updateSite(site.id, patch));
      setMsg({ ok: true, text: "Tersimpan." });
    } catch (err) {
      const r = readErrors(err);
      setMsg({ ok: false, text: r.fields.name ?? r.summary });
    } finally {
      setBusy(null);
    }
  };

  const useMyLocation = () => {
    if (!navigator.geolocation) { setMsg({ ok: false, text: "Browser ini tidak bisa membaca lokasi." }); return; }
    setBusy("gps"); setMsg(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setDraft({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setMsg({ ok: true, text: `Lokasi Anda dipakai (akurasi ±${Math.round(pos.coords.accuracy)} m). Klik "Simpan titik".` });
        setBusy(null);
      },
      () => { setMsg({ ok: false, text: "Lokasi tidak bisa dibaca. Izinkan akses lokasi di browser." }); setBusy(null); },
      { enableHighAccuracy: true, timeout: 20000 },
    );
  };

  const fenced = kind === "fixed" || kind === "moving";

  return (
    <div className="card" style={{ padding: 18 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 160px 140px auto", gap: 10, alignItems: "end", marginBottom: 6 }}>
        <div>
          <label className="label">Nama</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="label">Jenis</label>
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value as SiteKind)}>
            {(Object.keys(SITE_KIND_LABEL) as SiteKind[]).map((k) => <option key={k} value={k}>{SITE_KIND_LABEL[k]}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Kode proyek</label>
          <input className="input" value={code} onChange={(e) => setCode(e.target.value)} placeholder="opsional" />
        </div>
        <button className="btn-ghost" disabled={!infoChanged || busy !== null}
                onClick={() => saveInfo({ name, kind, project_code: code })} style={{ padding: "8px 14px" }}>
          Simpan
        </button>
      </div>
      <div style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 14 }}>{KIND_HELP[kind]}</div>

      <SiteMap pin={draft} radius={radius} focusKey={site.id} onPick={(lat, lng) => { setDraft({ lat, lng }); setMsg(null); }} />

      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", marginTop: 12 }}>
        <div style={{ fontSize: 13, color: "var(--ink-soft)", flex: "1 1 220px" }}>
          <MapPin size={14} style={{ verticalAlign: "-2px" }} />{" "}
          {draft ? `${draft.lat.toFixed(6)}, ${draft.lng.toFixed(6)}` : "Klik peta untuk menaruh titik"}
          {!fenced && " (opsional untuk jenis ini)"}
        </div>
        <button className="btn-ghost" onClick={useMyLocation} disabled={busy !== null} style={{ padding: "7px 12px", fontSize: 13 }}>
          {busy === "gps" ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite", verticalAlign: "-2px" }} />
                          : <Crosshair size={14} style={{ verticalAlign: "-2px" }} />} Lokasi saya
        </button>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginTop: 12 }}>
        <span className="label" style={{ margin: 0 }}>Radius</span>
        {RADIUS_PRESETS.map((r) => (
          <button key={r} onClick={() => setRadius(r)} className="pill"
                  style={{ border: "1px solid var(--line)", cursor: "pointer",
                           background: radius === r ? "var(--rust)" : "var(--paper-3)", color: radius === r ? "#fff" : "var(--ink)" }}>
            {r} m
          </button>
        ))}
        <input className="input" type="number" min={20} max={5000} value={radius}
               onChange={(e) => setRadius(Math.max(0, Number(e.target.value) || 0))} style={{ width: 100 }} />
        <span style={{ fontSize: 13, color: "var(--steel)" }}>meter (20-5000)</span>
        <button className="btn-rust" onClick={savePin} disabled={!draft || !pinChanged || busy !== null || radius < 20 || radius > 5000}
                style={{ marginLeft: "auto" }}>
          {busy === "pin" ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={15} />} Simpan titik
        </button>
      </div>

      {msg && <div style={{ marginTop: 12, fontSize: 13.5, fontWeight: 600, color: msg.ok ? "var(--workshop)" : "var(--danger)" }}>{msg.text}</div>}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 20, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
        <div className="label" style={{ margin: 0 }}>Riwayat titik</div>
        <button className="btn-ghost" onClick={() => saveInfo({ is_active: !site.is_active })} disabled={busy !== null}
                style={{ padding: "5px 12px", fontSize: 12.5 }}>
          {site.is_active ? "Nonaktifkan lokasi" : "Aktifkan lagi"}
        </button>
      </div>
      {(site.history ?? []).length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--steel)", marginTop: 8 }}>Belum ada titik.</div>
      ) : (
        <table className="data-table" style={{ marginTop: 6 }}>
          <thead><tr><th>Berlaku sejak</th><th>Koordinat</th><th>Radius</th></tr></thead>
          <tbody>
            {(site.history ?? []).map((h, i) => (
              <tr key={h.id}>
                <td style={{ fontSize: 13 }}>{dateTimeWIB(h.valid_from)}{i === 0 ? " (sekarang)" : ""}</td>
                <td className="mono" style={{ fontSize: 12.5 }}>{h.latitude.toFixed(6)}, {h.longitude.toFixed(6)}</td>
                <td style={{ fontSize: 13 }}>{h.radius_m} m</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function round6(n: number): number {
  return Math.round(n * 1e6) / 1e6;
}
