"use client";
// =============================================================================
// MachinesCard — "Mesin fingerprint" on the Lokasi page (G12f.1b, 9 Nov 2026).
// Mesin utama = the IDs on each employee ("ID Mesin Fingerprint"); always there, not editable here.
// Other machines: name, site, "Dept. di file" (for Anthony's combined report), on/off.
// A machine with IDs or taps can only be turned off; an unused one can be deleted.
// =============================================================================
import { Site, readErrors } from "@/lib/api/hr";
import { Machine, MachineInput, MachineList, machineApi } from "@/lib/api/machines";
import { Fingerprint, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { DeptChips } from "@/components/DeptBox";                        // G12f.3.5
import { useCallback, useEffect, useState } from "react";

const DEPT_HELP = "Isi kolom Dept. mesin ini di laporan gabungan, pisahkan dengan koma (mis. Staf, Manager). "
  + "Dipakai saat import \"Otomatis menurut Dept.\". Dept. yang tidak diisi di mesin mana pun masuk Mesin utama.";

export default function MachinesCard({ sites }: { sites: Site[] }) {
  const [list, setList] = useState<MachineList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<MachineInput>({ name: "", site: null, dept_labels: "", is_active: true });
  const [adding, setAdding] = useState(false);
  const [addErrors, setAddErrors] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try { setList(await machineApi.list()); setError(null); } catch (err) { setError(readErrors(err).summary); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const replace = (machines: Machine[]) => setList((cur) => (cur ? { ...cur, machines } : cur));

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setAdding(true); setAddErrors({});
    try {
      replace(await machineApi.create(draft));
      setDraft({ name: "", site: null, dept_labels: "", is_active: true });
    } catch (err) {
      const r = readErrors(err);
      setAddErrors({ ...r.fields, summary: r.summary });
    } finally {
      setAdding(false);
    }
  };

  const activeSites = sites.filter((s) => s.is_active);

  return (
    <div className="card" style={{ padding: 18, marginTop: 18 }}>
      <div style={{ fontWeight: 800, fontSize: 17, color: "var(--midnight)", display: "flex", alignItems: "center", gap: 8 }}>
        <Fingerprint size={18} /> Mesin fingerprint
      </div>
      <div style={{ fontSize: 13.5, color: "var(--steel)", margin: "4px 0 12px" }}>
        Satu mesin cukup? Tidak perlu isi apa-apa: ID di data karyawan adalah <b>Mesin utama</b>. Tambah mesin lain bila
        nomor ID-nya bisa sama dengan mesin utama (mis. mesin kantor dan mesin plant). ID tiap karyawan di mesin lain
        diisi di menu Karyawan.
      </div>
      {error && <div style={{ color: "var(--danger)", fontSize: 13.5, marginBottom: 10 }}>{error}</div>}
      {!list ? (
        <div style={{ color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>
      ) : (
        <>
          <table className="data-table">
            <thead><tr><th>Mesin</th><th>Lokasi</th><th>Dept. di file</th><th>Karyawan</th><th>Tap</th><th /></tr></thead>
            <tbody>
              <tr>
                <td style={{ fontWeight: 700 }}>{list.main.name}</td>
                <td style={{ fontSize: 13, color: "var(--steel)" }}>-</td>
                <td style={{ fontSize: 13, color: "var(--steel)" }}>semua yang lain</td>
                <td>{list.main.employees}</td>
                <td>{list.main.taps.toLocaleString("id-ID")}</td>
                <td style={{ fontSize: 12.5, color: "var(--steel)" }}>ID di data karyawan</td>
              </tr>
              {list.machines.map((m) => (
                <MachineRow key={m.id} machine={m} sites={sites} onChanged={replace} />
              ))}
            </tbody>
          </table>

          <form onSubmit={add} style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1.4fr auto", gap: 10, alignItems: "end",
                                        marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
            <div>
              <label className="label">Mesin baru</label>
              <input className="input" value={draft.name} placeholder="mis. Mesin Kantor"
                     onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                     style={addErrors.name ? { borderColor: "var(--danger)" } : undefined} />
            </div>
            <div>
              <label className="label">Lokasi (opsional)</label>
              <select className="input" value={draft.site ?? ""} onChange={(e) => setDraft({ ...draft, site: e.target.value || null })}>
                <option value="">-</option>
                {activeSites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Dept. di file (opsional)</label>
              <input className="input" value={draft.dept_labels} placeholder="mis. Staf, Manager"
                     onChange={(e) => setDraft({ ...draft, dept_labels: e.target.value })}
                     style={addErrors.dept_labels ? { borderColor: "var(--danger)" } : undefined} />
              {draft.dept_labels.trim() && <DeptChips text={draft.dept_labels} />}
            </div>
            <button className="btn-rust" disabled={adding || !draft.name.trim()} style={{ padding: "8px 14px" }}>
              {adding ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={15} />} Tambah mesin
            </button>
          </form>
          {(addErrors.name || addErrors.dept_labels || addErrors.summary) && (
            <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 6 }}>
              {addErrors.name ?? addErrors.dept_labels ?? addErrors.summary}
            </div>
          )}
          <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 8 }}>{DEPT_HELP}</div>
        </>
      )}
    </div>
  );
}

function MachineRow({ machine, sites, onChanged }: { machine: Machine; sites: Site[]; onChanged: (m: Machine[]) => void }) {
  const [name, setName] = useState(machine.name);
  const [site, setSite] = useState<string | null>(machine.site);
  const [dept, setDept] = useState(machine.dept_labels);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // take the saved values (the server tidies names and labels), but only when THIS machine changed,
  // so saving another row never wipes what HR is typing here
  useEffect(() => { setName(machine.name); setSite(machine.site); setDept(machine.dept_labels); },
            [machine.name, machine.site, machine.dept_labels]);

  const changed = name !== machine.name || site !== machine.site || dept !== machine.dept_labels;
  const inUse = machine.employees > 0 || machine.taps > 0;
  const siteOptions = sites.filter((s) => s.is_active || s.id === machine.site);

  const call = async (fn: () => Promise<Machine[]>, ok: string) => {
    setBusy(true); setMsg(null);
    try {
      onChanged(await fn());
      setMsg({ ok: true, text: ok });
    } catch (err) {
      const r = readErrors(err);
      setMsg({ ok: false, text: r.fields.name ?? r.fields.dept_labels ?? r.summary });
    } finally {
      setBusy(false);
    }
  };

  const remove = () => {
    if (!window.confirm(`Hapus ${machine.name}? Mesin ini belum punya ID karyawan maupun tap.`)) return;
    call(() => machineApi.remove(machine.id), "Dihapus.");
  };

  return (
    <tr style={{ opacity: machine.is_active ? 1 : 0.6 }}>
      <td>
        <input className="input" value={name} onChange={(e) => { setName(e.target.value); setMsg(null); }} style={{ minWidth: 140 }} />
        {!machine.is_active && <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 2 }}>nonaktif</div>}
        {msg && <div style={{ fontSize: 12.5, marginTop: 4, color: msg.ok ? "var(--workshop)" : "var(--danger)" }}>{msg.text}</div>}
      </td>
      <td>
        <select className="input" value={site ?? ""} onChange={(e) => { setSite(e.target.value || null); setMsg(null); }}>
          <option value="">-</option>
          {siteOptions.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </td>
      <td>
        <input className="input" value={dept} placeholder="mis. Staf, Manager" onChange={(e) => { setDept(e.target.value); setMsg(null); }} />
        <DeptChips text={dept} />
      </td>
      <td>{machine.employees}</td>
      <td>{machine.taps.toLocaleString("id-ID")}</td>
      <td style={{ whiteSpace: "nowrap" }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button className="btn-ghost" disabled={!changed || busy} style={{ padding: "6px 10px" }}
                  onClick={() => call(() => machineApi.update(machine.id, { name, site, dept_labels: dept }), "Tersimpan.")}>
            {busy ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={14} />} Simpan
          </button>
          <button className="btn-ghost" disabled={busy} style={{ padding: "6px 10px", fontSize: 12.5 }}
                  onClick={() => call(() => machineApi.update(machine.id, { is_active: !machine.is_active }),
                                     machine.is_active ? "Dinonaktifkan." : "Diaktifkan lagi.")}>
            {machine.is_active ? "Nonaktifkan" : "Aktifkan"}
          </button>
          {!inUse && (
            <button className="btn-ghost" disabled={busy} onClick={remove} aria-label={`Hapus ${machine.name}`}
                    style={{ padding: "6px 8px", color: "var(--danger)" }}>
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
