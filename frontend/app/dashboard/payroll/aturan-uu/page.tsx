"use client";
// =============================================================================
// /dashboard/payroll/aturan-uu — "Aturan perusahaan vs UU" (G18-1, 19 Nov 2026).
// Read-only: where the company's settings and data stand against UU No. 27 Tahun 2026. Information only:
// nothing is blocked, no score. Each row links to the page where the setting lives.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { LawCheck, LawRow, payrollApi } from "@/lib/api/payroll";
import { ArrowLeft, CheckCircle2, CircleDashed, Info, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"];
const dateText = (iso: string) => { const [y, m, d] = iso.split("-").map(Number); return y ? `${d} ${MONTHS[m - 1]} ${y}` : iso; };

const GROUPS: { title: string; statuses: LawRow["status"][]; color: string; bg: string }[] = [
  { title: "Berbeda dari UU", statuses: ["differs", "found"], color: "#2563A8", bg: "#E7F1FB" },
  { title: "Perlu dilengkapi", statuses: ["missing"], color: "var(--steel)", bg: "#F3F5F8" },
  { title: "Sesuai UU", statuses: ["ok"], color: "#2E7D4F", bg: "#FFFFFF" },
];

function Icon({ status }: { status: LawRow["status"] }) {
  if (status === "ok") return <CheckCircle2 size={16} style={{ color: "#2E7D4F", flexShrink: 0, marginTop: 2 }} />;
  if (status === "missing") return <CircleDashed size={16} style={{ color: "var(--steel)", flexShrink: 0, marginTop: 2 }} />;
  return <Info size={16} style={{ color: "#2563A8", flexShrink: 0, marginTop: 2 }} />;
}

function RowCard({ row, bg }: { row: LawRow; bg: string }) {
  return (
    <div style={{ display: "flex", gap: 10, padding: "12px 14px", background: bg, borderRadius: 10, marginBottom: 8,
                  border: "1px solid #E3E8EF" }}>
      <Icon status={row.status} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div style={{ fontWeight: 700, color: "var(--midnight)" }}>{row.title}</div>
          <Link href={row.link} style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap" }}>{row.link_text} →</Link>
        </div>
        <div style={{ fontSize: 13.5, marginTop: 2 }}><span style={{ color: "var(--steel)" }}>Perusahaan:</span> {row.company}</div>
        <div style={{ fontSize: 13.5 }}><span style={{ color: "var(--steel)" }}>UU:</span> {row.law} ({row.article})</div>
        {row.people.length > 0 && (
          <div style={{ fontSize: 13, marginTop: 4 }}>{row.people.join(" · ")}</div>
        )}
        {row.changed && <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 4 }}>{row.changed}</div>}
      </div>
    </div>
  );
}

export default function LawCheckPage() {
  const [data, setData] = useState<LawCheck | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    payrollApi.lawCheck().then(setData).catch((e) => setError(readErrors(e).summary));
  }, []);

  return (
    <div style={{ maxWidth: 820 }}>
      <Link href="/dashboard/payroll/pengaturan" style={{ fontSize: 13.5, display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <ArrowLeft size={14} /> Pengaturan payroll
      </Link>
      <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Aturan perusahaan vs UU</h1>
      {data && (
        <div style={{ fontSize: 13.5, color: "var(--steel)", marginBottom: 16 }}>
          Dibandingkan dengan {data.law} (berlaku {dateText(data.effective)}), per {dateText(data.as_of)}.
          Hanya info: SeeGaji tidak memblokir apa pun. Pilihan tetap di tangan perusahaan.
        </div>
      )}
      {error && <div className="card" style={{ color: "var(--danger)" }}>{error}</div>}
      {!data && !error && <div style={{ padding: 24 }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /></div>}
      {data && GROUPS.map((g) => {
        const rows = data.rows.filter((r) => g.statuses.includes(r.status));
        if (rows.length === 0) return null;
        return (
          <div key={g.title} style={{ marginBottom: 18 }}>
            <div className="label" style={{ color: g.color, marginBottom: 6 }}>{g.title} ({rows.length})</div>
            {rows.map((r) => <RowCard key={r.key} row={r} bg={g.bg} />)}
          </div>
        );
      })}
    </div>
  );
}
