"use client";
// seegaji.com/ — the public landing page (11 Nov 2026).
// Look: Midnight & Marigold with a batik (kawung) relief on the dark sections, glass cards on dark,
// soft neumorphic cards on light. Every number on this page is either true (DKCB facts) or labelled "contoh".
// Styles live in ./landing.css; every class starts with lp- so nothing leaks into the app.
import LogoMark from "@/components/LogoMark";
import Link from "next/link";
import { useState } from "react";
import "./landing.css";

const WA_NUMBER = "6281275888768";
const WA_TEXT = "Halo, saya ingin jadwalkan demo SeeGaji untuk perusahaan saya.";
const WA = `https://wa.me/${WA_NUMBER}?text=${encodeURIComponent(WA_TEXT)}`;

type Code = "H" | "TP" | "A" | "C" | "DL" | "L" | "LK";
const START: Code[] = ["H", "TP", "H", "H", "H", "H", "L"];
const WEEKDAY: Code[] = ["H", "TP", "A", "C", "DL"];
const WEEKEND: Code[] = ["L", "LK"];
const LABELS = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"];
const NAMES = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"];
const EXPLAIN: Record<Code, string> = {
  H: "Hadir tepat waktu: dapat uang makan, tanpa potongan.",
  TP: "Telat: tetap dapat uang makan, tapi ada potongan telat.",
  A: "Alpa: tidak hadir tanpa keterangan, upah hari itu dipotong.",
  C: "Cuti: upah tetap dibayar, tanpa uang makan. Saldo cuti berkurang satu.",
  DL: "Tidak wajib absen (misalnya bertugas di lokasi lain): dihitung hadir, tanpa uang makan.",
  L: "Libur: tidak ada yang dihitung.",
  LK: "Lembur di hari libur: ada tambahan lembur hari libur.",
};
// Example rules for the playground only (labelled "contoh" on the page).
const DAY_PAY = 150_000, MEAL = 20_000, LATE = 25_000, HOLIDAY_OT = 250_000;

type Tab = { name: string; title: string; lead: string; points: string[]; cardTitle: string; badge: string; rows: [string, string][] };
const TABS: Tab[] = [
  { name: "Absensi", title: "Mesin fingerprint atau HP, hasilnya satu.", lead: "Karyawan bisa absen di mesin fingerprint atau lewat HP. Keduanya berakhir di Rekap yang sama.",
    points: ["Beberapa mesin sekaligus, masing-masing dengan nomor ID sendiri", "Absen HP dengan foto dan lokasi, hanya di area kerja", "Shift malam yang lewat tengah malam tetap dihitung satu hari"],
    cardTitle: "IMPORT · MESIN UTAMA", badge: "Pratinjau", rows: [["File", "Absensi Nov.xls"], ["Hari baru", "23"], ["Nama tidak cocok", "0"], ["Mesin", "Mesin utama"]] },
  { name: "Perlu Tinjau", title: "Hanya yang perlu diputuskan.", lead: "Hari yang normal langsung beres. HR hanya melihat hari yang memang butuh keputusan.",
    points: ["Lupa tap pulang: isi jamnya dalam satu klik", "Lembur: setujui atau tolak, sendiri-sendiri atau sekaligus", "Telat: maafkan atau potong, dengan alasan yang tercatat"],
    cardTitle: "PERLU TINJAU", badge: "4 hari", rows: [["Budi · Sel", "Lupa tap pulang"], ["Sari · Rab", "Lembur 2 jam"], ["Andi · Kam", "Telat 21 menit"], ["Dewi · Sab", "Tap di hari libur"]] },
  { name: "Rekap", title: "Satu baris per orang, satu kode per hari.", lead: "Rekap periode menunjukkan kode setiap hari, total lembur dan uang makan. Unduh ke Excel bila perlu.",
    points: ["Kode yang sama dengan kebiasaan HR: H, TP, A, C, L, LK", "Catatan HR tampil di sudut kotak hari", "Periode gaji sesuai perusahaan, misalnya tanggal 26 sampai 25"],
    cardTitle: "REKAP · 26 OKT – 25 NOV", badge: "Excel", rows: [["Hadir", "22 hari"], ["Telat", "2 hari"], ["Lembur", "14 jam"], ["Uang makan", "24 hari"]] },
  { name: "Payroll & Slip", title: "Dari Rekap ke slip, tanpa salin-tempel.", lead: "Payroll mengambil angka dari Rekap yang sama. Item tambahan seperti kasbon atau bonus diketik sekali.",
    points: ["Cek dulu, lalu kunci. Bulan terkunci tidak bisa berubah", "Slip A5 siap cetak untuk setiap karyawan", "File transfer bank siap diunggah"],
    cardTitle: "PAYROLL · NOV 2026", badge: "Terkunci", rows: [["Karyawan", "30"], ["Slip A5", "Siap cetak"], ["File bank", "Siap unduh"], ["Peringatan", "1 untuk dicek"]] },
  { name: "Cuti & Izin", title: "Pengajuan dari HP, saldo terhitung sendiri.", lead: "Karyawan mengajukan cuti atau izin dari HP. HR menyetujui, atau mencatat dari formulir kertas.",
    points: ["Saldo cuti berkurang otomatis", "Cuti yang disetujui langsung muncul di Rekap", "Tidak ada lagi formulir yang hilang di laci"],
    cardTitle: "PENGAJUAN", badge: "2 baru", rows: [["Rina", "Cuti 2 hari"], ["Joko", "Izin sakit"], ["Sisa cuti Rina", "8 hari"]] },
  { name: "Catatan HR", title: "Alasan di balik hari yang aneh.", lead: "Mati lampu, bertugas di luar, sakit dengan surat dokter. Catatan HR menempel di hari itu dan tidak pernah mengubah uang diam-diam.",
    points: ["Catatan lama dari Excel dibaca otomatis, termasuk warnanya", "Tidak wajib absen untuk staf yang bertugas di lokasi lain", "Semua perubahan tercatat: siapa, kapan, apa"],
    cardTitle: "CATATAN · 14 OKT", badge: "HR", rows: [["Semua karyawan", "Mati lampu"], ["Marga", "Bertugas di lokasi lain"], ["Dibuat oleh", "HR"]] },
];

const FAQS: [string, string][] = [
  ["Mesin fingerprint apa saja yang bisa dipakai?", "Mesin yang bisa mengekspor laporan absensi ke file Excel. SeeGaji membaca file itu apa adanya, termasuk dari beberapa mesin dengan nomor ID yang berbeda."],
  ["Apakah perlu instal sesuatu?", "Tidak. SeeGaji dibuka lewat browser di komputer HR. Karyawan yang absen lewat HP cukup membuka tautan di HP-nya."],
  ["Bagaimana dengan data Excel kami yang lama?", "Kartu Persiapan awal memandu pindahan langkah demi langkah: daftar karyawan, mesin, aturan, sampai catatan HR dari Excel. Setiap langkah tercentang sendiri begitu datanya masuk."],
  ["Aturan perusahaan kami berbeda. Bisa?", "Bisa. Jam kerja, toleransi telat, uang makan, lembur dan periode gaji diatur sekali sesuai perusahaan Anda. Angka di halaman ini hanya contoh."],
  ["Di mana data kami disimpan, dan siapa yang bisa melihat?", "Di server yang dikelola Langit, dengan koneksi HTTPS dan cadangan setiap malam. Data setiap perusahaan terpisah, dan hanya akun perusahaan Anda yang bisa melihatnya."],
  ["Kapan BPJS dan PPh 21 tersedia?", "Sedang disusun bersama konsultan pajak. Kami kabari begitu siap. Sementara itu, angkanya bisa dimasukkan sebagai item payroll."],
];

const rp = (n: number) => "Rp " + Math.round(n).toLocaleString("id-ID");

/* ---------- small pieces ---------- */
function Kawung({ id, masked = false }: { id: string; masked?: boolean }) {
  return (
    <svg className="lp-pattern" aria-hidden="true">
      <defs>
        <pattern id={`${id}-p`} width="96" height="96" patternUnits="userSpaceOnUse">
          <g fill="none" stroke="rgba(169,195,210,.13)" strokeWidth="1.6">
            <ellipse cx="48" cy="24" rx="13" ry="21" /><ellipse cx="48" cy="72" rx="13" ry="21" />
            <ellipse cx="24" cy="48" rx="21" ry="13" /><ellipse cx="72" cy="48" rx="21" ry="13" />
            <circle cx="48" cy="48" r="3.5" />
            <circle cx="0" cy="0" r="5" /><circle cx="96" cy="0" r="5" /><circle cx="0" cy="96" r="5" /><circle cx="96" cy="96" r="5" />
          </g>
        </pattern>
        {masked && (
          <>
            <radialGradient id={`${id}-g`} cx="25%" cy="40%" r="75%">
              <stop offset="0" stopColor="#fff" stopOpacity="0" /><stop offset=".55" stopColor="#fff" stopOpacity=".9" /><stop offset="1" stopColor="#fff" stopOpacity="1" />
            </radialGradient>
            <mask id={`${id}-m`}><rect width="100%" height="100%" fill={`url(#${id}-g)`} /></mask>
          </>
        )}
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id}-p)`} mask={masked ? `url(#${id}-m)` : undefined} />
    </svg>
  );
}

function Check({ color = "#F5A623", size = 18, width = 2.4 }: { color?: string; size?: number; width?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>;
}

function WaIcon() {
  return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5a8.4 8.4 0 0 1-12.4 7.4L3 20.5l1.6-5.4A8.4 8.4 0 1 1 21 11.5z" /></svg>;
}

function Icon({ d, children }: { d?: string; children?: React.ReactNode }) {
  return <svg aria-hidden="true" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#FFC255" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{d ? <path d={d} /> : children}</svg>;
}

/* ---------- the page ---------- */
export default function Landing({ appHref }: { appHref: string | null }) {
  const [week, setWeek] = useState<Code[]>(START);
  const [last, setLast] = useState(1);
  const [tab, setTab] = useState(0);
  const [faq, setFaq] = useState(0);

  const cycle = (i: number) => {
    const list = i === 6 ? WEEKEND : WEEKDAY;
    const next = list[(list.indexOf(week[i]) + 1) % list.length];
    setWeek(week.map((c, j) => (j === i ? next : c)));
    setLast(i);
  };
  const count = (c: Code) => week.filter((x) => x === c).length;
  const mealDays = count("H") + count("TP"), lateDays = count("TP"), absDays = count("A");
  const base = 6 * DAY_PAY, meal = mealDays * MEAL, ot = count("LK") * HOLIDAY_OT, late = lateDays * LATE, abs = absDays * DAY_PAY;
  const t = TABS[tab];
  const app = appHref ?? "/login";
  const appLabel = appHref ? "Buka SeeGaji" : "Masuk";

  return (
    <div className="lp">
      {/* ============ HERO ============ */}
      <header className="lp-dark">
        <Kawung id="kw-hero" masked />
        <div className="lp-lamp lp-glow" aria-hidden="true" style={{ right: -160, top: -140, width: 620, height: 620 }} />

        <nav className="lp-wrap lp-nav" aria-label="Utama">
          <a href="#top" className="lp-brand">
            <LogoMark size={42} onDark />
            <span className="lp-brand-word">See<span className="lp-gold">Gaji</span></span>
          </a>
          <div className="lp-navlinks">
            <a href="#cara">Cara kerja</a><a href="#coba">Coba sendiri</a><a href="#fitur">Fitur</a><a href="#harga">Harga</a><a href="#faq">FAQ</a>
          </div>
          <div className="lp-row" style={{ gap: 10 }}>
            <Link className="lp-btn lp-btn-ghost lp-btn-sm" href={app}>{appLabel}</Link>
            <a className="lp-btn lp-btn-gold lp-btn-sm lp-hide-sm" href={WA} target="_blank" rel="noopener noreferrer">Jadwalkan demo</a>
          </div>
        </nav>

        <div className="lp-wrap lp-hero-grid lp-hero" id="top">
          <div>
            <div className="lp-badge lp-glass lp-glass-flat"><b>PILOT</b>Dibangun bersama HR DKCB, Tanjung Uban</div>
            <h1 className="lp-h1">Dari mesin fingerprint ke slip gaji. <span className="lp-gold">Tanpa rumus Excel.</span></h1>
            <p className="lp-hero-p">SeeGaji membaca file dari mesin absen, menghitung telat, lembur dan uang makan sesuai aturan perusahaan Anda, lalu menyiapkan slip dan file transfer bank. HR cukup memeriksa yang memang perlu diputuskan.</p>
            <div className="lp-row" style={{ marginTop: 36 }}>
              <a className="lp-btn lp-btn-gold" href={WA} target="_blank" rel="noopener noreferrer"><WaIcon />Jadwalkan demo via WhatsApp</a>
              <a className="lp-btn lp-btn-ghost" href="#coba">Coba hitung sendiri</a>
            </div>
            <div className="lp-ticks">
              <span><Check />Tanpa instal</span><span><Check />Bahasa Indonesia yang mudah</span><span><Check />Mesin fingerprint atau HP</span>
            </div>
          </div>

          <div className="lp-stage" aria-hidden="true">
            <div className="lp-orb lp-orb-gold lp-f1" style={{ left: -30, top: -10, width: 90, height: 90 }} />
            <div className="lp-orb lp-orb-blue lp-f2" style={{ right: -10, bottom: 10, width: 70, height: 70 }} />
            <div className="lp-glass" style={{ position: "absolute", left: 0, top: 30, width: 250, borderRadius: 24, padding: 20 }}>
              <div className="lp-mini-label">TAP DARI MESIN</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
                {[["Sen", "07:52", false], ["Sen", "17:04", false], ["Sel", "08:21", true], ["Sel", "17:10", false]].map(([d, h, warn], i) => (
                  <div key={i} className="lp-tap lp-anim-tap" style={{ animationDelay: `${i * 0.25}s` }}>
                    <span>Rina · {d}</span><span style={{ fontWeight: 700, color: warn ? "#FFC255" : undefined }}>{h}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="lp-glass lp-rekap" style={{ position: "absolute", right: 10, top: 0, width: 300, borderRadius: 24, padding: 20 }}>
              <div className="lp-mini-label">REKAP · NOV</div>
              <div className="lp-mini-grid">
                {["S", "S", "R", "K", "J", "S", "M"].map((d, i) => <span key={i}>{d}</span>)}
                {(["H", "TP", "H", "H", "C", "H", "LK"] as Code[]).map((c, i) => (
                  <span key={i} className={`lp-mini-code lp-c-${c} lp-anim-code`} style={{ animationDelay: `${1.4 + i * 0.15}s` }}>{c}</span>
                ))}
              </div>
              <div className="lp-between" style={{ marginTop: 16, fontSize: 13, color: "#C9DAE5" }}><span>Lembur</span><b style={{ color: "#FFFFFF" }}>7 jam</b></div>
              <div className="lp-between" style={{ marginTop: 6, fontSize: 13, color: "#C9DAE5" }}><span>Uang makan</span><b style={{ color: "#FFFFFF" }}>5 hari</b></div>
            </div>
            <div className="lp-slip lp-anim-slip">
              <div className="lp-between">
                <span style={{ fontSize: 12, fontWeight: 800, letterSpacing: ".08em", color: "#4F6372" }}>SLIP GAJI · A5</span>
                <span className="lp-pill lp-c-H">Terkunci</span>
              </div>
              <div style={{ marginTop: 14, fontSize: 18, fontWeight: 800 }}>Rina Lestari</div>
              <div style={{ fontSize: 13, color: "#4F6372" }}>Contoh · periode 26 Okt – 25 Nov</div>
              <div style={{ height: 1, background: "#DCE8F0", margin: "14px 0" }} />
              <div className="lp-line"><span>Gaji pokok</span><span>4.000.000</span></div>
              <div className="lp-line"><span>Lembur</span><span>+ 312.000</span></div>
              <div className="lp-line"><span>Uang makan</span><span>+ 500.000</span></div>
              <div className="lp-line" style={{ color: "#B42318" }}><span>Potongan telat</span><span>− 50.000</span></div>
              <div className="lp-net"><span>Diterima</span><span>Rp 4.762.000</span></div>
            </div>
          </div>
        </div>
      </header>

      {/* ============ DKCB STRIP ============ */}
      <section className="lp-strip-wrap" aria-label="Pilot DKCB">
        <div className="lp-wrap">
          <div className="lp-neu lp-strip">
            <div className="lp-row" style={{ gap: 18 }}>
              <div className="lp-dkcb">DKCB</div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: ".08em", color: "#4F6372" }}>PILOT PERTAMA</div>
                <div style={{ fontSize: 22, fontWeight: 800, color: "#013D5A" }}>DKCB · Tanjung Uban, Bintan</div>
              </div>
            </div>
            <div className="lp-row" style={{ gap: 36 }}>
              <div><div className="lp-stat-n">±30</div><div className="lp-stat-l">karyawan</div></div>
              <div><div className="lp-stat-n">2</div><div className="lp-stat-l">mesin fingerprint</div></div>
              <div><div className="lp-stat-n">26–25</div><div className="lp-stat-l">periode gaji</div></div>
            </div>
            <a href="#dkcb" style={{ fontWeight: 700, textDecoration: "none", display: "inline-flex", gap: 8, alignItems: "center", minHeight: 44 }}>
              Lihat ceritanya
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
            </a>
          </div>
        </div>
      </section>

      {/* ============ OLD WAY ============ */}
      <section className="lp-sec-top">
        <div className="lp-wrap">
          <div className="lp-head">
            <div className="lp-eyebrow">AKHIR BULAN HR, VERSI LAMA</div>
            <h2 className="lp-h2">Tiga hari mewarnai sel Excel, lalu memeriksanya lagi dari awal.</h2>
          </div>
          <div className="lp-auto4 lp-mt48">
            {[
              ["1", "Export dari mesin", "Satu file per mesin, empat sheet, kolom yang berbeda-beda."],
              ["2", "Warnai sel satu per satu", "Kuning untuk telat, merah untuk alpa, hijau untuk lembur. Ratusan sel."],
              ["3", "Hitung manual", "Jam lembur, potongan telat, uang makan, dengan rumus yang hanya dipahami satu orang."],
              ["4", "Cek ulang. Lagi.", "Satu salah ketik berarti slip salah, dan karyawan yang kecewa."],
            ].map(([n, title, text]) => (
              <div key={n} className="lp-neu lp-card">
                <div className="lp-neu-in lp-num" style={n === "4" ? { color: "#B42318" } : undefined}>{n}</div>
                <div className="lp-card-t">{title}</div>
                <p className="lp-card-p">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============ 3 STEPS ============ */}
      <section id="cara" className="lp-sec-bot">
        <div className="lp-wrap">
          <div className="lp-head">
            <div className="lp-eyebrow">DENGAN SEEGAJI</div>
            <h2 className="lp-h2">Satu periode gaji, tiga langkah.</h2>
          </div>
          <div className="lp-steps lp-mt48">
            <div className="lp-neu lp-step">
              <span className="lp-step-tag">Langkah 1</span>
              <div className="lp-step-t">Import file mesin</div>
              <p className="lp-card-p" style={{ marginTop: 0 }}>Pilih file Excel dari mesin. Sebelum menyimpan, SeeGaji menjelaskan apa yang akan masuk, dengan kalimat biasa.</p>
              <div className="lp-neu-in lp-inset">
                <div className="lp-between"><span>Hari baru</span><b style={{ color: "#1E7F4F" }}>23</b></div>
                <div className="lp-between"><span>Sudah ada</span><b>2</b></div>
                <div className="lp-between"><span>Nama tidak cocok</span><b style={{ color: "#1E7F4F" }}>0</b></div>
              </div>
            </div>
            <div className="lp-neu lp-step">
              <span className="lp-step-tag">Langkah 2</span>
              <div className="lp-step-t">Selesaikan Perlu Tinjau</div>
              <p className="lp-card-p" style={{ marginTop: 0 }}>Hanya hari yang butuh keputusan: lupa tap pulang, lembur yang perlu disetujui, telat yang mau dimaafkan.</p>
              <div className="lp-neu-in lp-inset" style={{ gap: 10 }}>
                <div className="lp-between"><span>Budi · lupa tap pulang</span><span className="lp-pill lp-c-TP">Isi jam</span></div>
                <div className="lp-between"><span>Sari · lembur 2 jam</span><span className="lp-pill lp-c-H">Setujui</span></div>
              </div>
            </div>
            <div className="lp-step lp-step-dark">
              <span className="lp-step-tag">Langkah 3</span>
              <div className="lp-step-t">Jalankan payroll</div>
              <p className="lp-card-p lp-card-p-dark" style={{ marginTop: 0 }}>Angka diambil dari Rekap yang sama, jadi slip dan Rekap selalu cocok. Kunci, cetak slip A5, unduh file transfer bank.</p>
              <div className="lp-glass lp-glass-flat lp-inset">
                <div className="lp-between"><span>Slip siap</span><b>30</b></div>
                <div className="lp-between"><span>File bank</span><b style={{ color: "#FFC255" }}>Unduh</b></div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ============ PLAYGROUND ============ */}
      <section id="coba" className="lp-sec lp-play">
        <div className="lp-orb lp-f1" aria-hidden="true" style={{ right: "6%", top: 60, width: 120, height: 120, background: "radial-gradient(circle at 30% 30%, #FFE2A6, #F5A623 60%, #C98510)", boxShadow: "18px 24px 40px rgba(1,61,90,.18)" }} />
        <div className="lp-orb lp-f2" aria-hidden="true" style={{ left: "3%", bottom: 70, width: 80, height: 56, background: "radial-gradient(circle at 35% 30%, #FFFFFF, #D5E0E8 70%)", boxShadow: "10px 16px 30px rgba(1,61,90,.18)" }} />
        <div className="lp-wrap lp-rel">
          <div className="lp-head">
            <div className="lp-eyebrow">COBA SENDIRI</div>
            <h2 className="lp-h2">Klik satu hari. Lihat slipnya ikut berubah.</h2>
            <p className="lp-lead">Ini cara SeeGaji berpikir: setiap kode di Rekap langsung menjadi angka di slip. Klik kotak hari untuk mengganti statusnya.</p>
          </div>
          <div className="lp-two lp-stretch lp-mt48">
            <div className="lp-neu" style={{ borderRadius: 28, padding: 28 }}>
              <div className="lp-between" style={{ flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: "#013D5A" }}>Rina Lestari · satu minggu</div>
                  <div style={{ fontSize: 14, color: "#4F6372" }}>Contoh. Aturan dan angka disesuaikan per perusahaan.</div>
                </div>
                <button type="button" className="lp-tab lp-tab-soft" onClick={() => { setWeek(START); setLast(1); }}>Ulangi</button>
              </div>
              <div className="lp-week">
                {week.map((c, i) => (
                  <div key={i} className="lp-day">
                    <span>{LABELS[i]}</span>
                    <button type="button" className={`lp-cell lp-c-${c}`} onClick={() => cycle(i)} aria-label={`${NAMES[i]}: ${c}. Klik untuk ganti status`}>{c}</button>
                  </div>
                ))}
              </div>
              <div className="lp-neu-in lp-explain" aria-live="polite">
                <b style={{ color: "#013D5A" }}>{NAMES[last]} ({week[last]}):</b> {EXPLAIN[week[last]]}
              </div>
              <div className="lp-legend">
                {([["H", "hadir"], ["TP", "telat"], ["A", "alpa"], ["C", "cuti"], ["DL", "tidak wajib absen"], ["L", "libur"], ["LK", "lembur hari libur"]] as [Code, string][]).map(([c, l]) => (
                  <span key={c} className={`lp-pill lp-c-${c}`}>{c} {l}</span>
                ))}
              </div>
            </div>

            <div className="lp-slipbig">
              <div className="lp-between">
                <span style={{ fontSize: 13, fontWeight: 800, letterSpacing: ".08em", color: "#4F6372" }}>SLIP MINGGUAN · CONTOH</span>
                <span className="lp-pill lp-c-LK">Langsung dihitung</span>
              </div>
              <div style={{ marginTop: 16, fontSize: 22, fontWeight: 800 }}>Rina Lestari</div>
              <div style={{ height: 1, background: "#DCE8F0", margin: "18px 0" }} />
              <div className="lp-line"><span>Upah 6 hari × {rp(DAY_PAY)}</span><span style={{ fontWeight: 600 }}>{rp(base)}</span></div>
              <div className="lp-line"><span>Uang makan ({mealDays} hari × {rp(MEAL)})</span><span className="lp-plus">+ {rp(meal)}</span></div>
              <div className="lp-line"><span>Lembur hari libur</span><span className="lp-plus">+ {rp(ot)}</span></div>
              <div className="lp-line"><span>Potongan telat ({lateDays} × {rp(LATE)})</span><span className="lp-minus">− {rp(late)}</span></div>
              <div className="lp-line"><span>Potongan alpa ({absDays} × {rp(DAY_PAY)})</span><span className="lp-minus">− {rp(abs)}</span></div>
              <div style={{ flexGrow: 1 }} />
              <div className="lp-netbig"><span>Diterima</span><span style={{ color: "#FFC255" }}>{rp(base + meal + ot - late - abs)}</span></div>
              <div style={{ fontSize: 13, color: "#4F6372", marginTop: 12 }}>Angka contoh untuk demo. Di SeeGaji, aturan diisi sekali sesuai perusahaan Anda.</div>
            </div>
          </div>
        </div>
      </section>

      {/* ============ FEATURES ============ */}
      <section id="fitur" className="lp-sec">
        <div className="lp-wrap">
          <div className="lp-head">
            <div className="lp-eyebrow">FITUR</div>
            <h2 className="lp-h2">Semua yang HR kerjakan tiap bulan, di satu tempat.</h2>
          </div>
          <div className="lp-neu-in lp-tabs" role="tablist" aria-label="Fitur">
            {TABS.map((x, i) => (
              <button key={x.name} type="button" role="tab" aria-selected={i === tab} className={`lp-tab${i === tab ? " lp-tab-on" : ""}`} onClick={() => setTab(i)}>{x.name}</button>
            ))}
          </div>
          <div className="lp-two lp-mt36" role="tabpanel">
            <div>
              <div style={{ fontSize: 30, fontWeight: 800, color: "#013D5A", lineHeight: 1.2 }}>{t.title}</div>
              <p className="lp-lead" style={{ marginTop: 14 }}>{t.lead}</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 22 }}>
                {t.points.map((p) => <div key={p} className="lp-point"><i><Check color="#7A4A00" size={14} width={3} /></i><span>{p}</span></div>)}
              </div>
            </div>
            <div className="lp-screen">
              <Kawung id="kw-screen" />
              <div className="lp-glass lp-rel" style={{ borderRadius: 22, padding: 22, color: "#FFFFFF" }}>
                <div className="lp-between">
                  <span className="lp-mini-label">{t.cardTitle}</span>
                  <span className="lp-pill" style={{ background: "#F5A623", color: "#2B1A00", fontWeight: 800 }}>{t.badge}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 16 }}>
                  {t.rows.map(([k, v]) => <div key={k} className="lp-screen-row"><span style={{ color: "#DCE8F0" }}>{k}</span><b>{v}</b></div>)}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ============ TRUST ============ */}
      <section className="lp-dark lp-dark-flat lp-sec">
        <Kawung id="kw-trust" />
        <div className="lp-lamp lp-glow" aria-hidden="true" style={{ left: -200, bottom: -220, width: 600, height: 600 }} />
        <div className="lp-wrap lp-rel">
          <div className="lp-head">
            <div className="lp-eyebrow lp-eyebrow-dark">PRINSIP KAMI</div>
            <h2 className="lp-h2 lp-h2-light">Tidak ada yang berubah diam-diam.</h2>
            <p className="lp-lead lp-lead-dark">Gaji adalah uang orang. Karena itu SeeGaji selalu bilang dulu apa yang akan terjadi, dan mencatat siapa mengubah apa.</p>
          </div>
          <div className="lp-auto3 lp-mt48">
            <div className="lp-glass lp-card"><Icon><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></Icon>
              <div className="lp-card-t">Pratinjau dulu, simpan kemudian</div><p className="lp-card-p lp-card-p-dark">Setiap import menjelaskan apa yang akan masuk, apa yang sudah ada, dan apa yang dilewati.</p></div>
            <div className="lp-glass lp-card"><Icon><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></Icon>
              <div className="lp-card-t">Payroll terkunci tetap terkunci</div><p className="lp-card-p lp-card-p-dark">Bulan yang sudah dibayar tidak bisa berubah karena data baru atau pengaturan baru.</p></div>
            <div className="lp-glass lp-card"><Icon><path d="M12 8v4l3 2" /><circle cx="12" cy="12" r="9" /></Icon>
              <div className="lp-card-t">Jejak setiap perubahan</div><p className="lp-card-p lp-card-p-dark">Siapa, kapan, dari berapa ke berapa. Semua tercatat dan bisa dilihat kembali.</p></div>
            <div className="lp-glass lp-card"><Icon><circle cx="9" cy="8" r="4" /><path d="M2 21a7 7 0 0 1 14 0" /><path d="m17 11 2 2 4-4" /></Icon>
              <div className="lp-card-t">Setiap nama dicek</div><p className="lp-card-p lp-card-p-dark">Nomor ID di mesin dicocokkan dengan nama karyawan. Yang tidak cocok ditandai merah, bukan disimpan diam-diam.</p></div>
            <div className="lp-glass lp-card"><Icon d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3z" />
              <div className="lp-card-t">Data terlindungi</div><p className="lp-card-p lp-card-p-dark">Koneksi HTTPS, data tiap perusahaan terpisah, dan cadangan otomatis setiap malam.</p></div>
            <div className="lp-glass lp-card"><Icon d="M4 5h16M4 12h10M4 19h7" />
              <div className="lp-card-t">Bahasa yang dimengerti</div><p className="lp-card-p lp-card-p-dark">Setiap pesan bilang artinya apa dan harus melakukan apa. Tanpa istilah teknis.</p></div>
          </div>
        </div>
      </section>

      {/* ============ DKCB STORY ============ */}
      <section id="dkcb" className="lp-sec-top">
        <div className="lp-wrap">
          <div className="lp-neu lp-dkcb-story" style={{ borderRadius: 36, padding: 48, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 40, alignItems: "center" }}>
            <div>
              <div className="lp-eyebrow">CERITA PILOT</div>
              <h2 className="lp-h2" style={{ fontSize: "clamp(30px, 4vw, 40px)" }}>Dibangun di lapangan, bersama HR DKCB.</h2>
              <p className="lp-lead" style={{ marginTop: 18, lineHeight: 1.7 }}>SeeGaji tidak dirancang dari meja. Setiap aturan diambil dari cara kerja HR DKCB di Tanjung Uban: dua mesin fingerprint dengan nomor ID sendiri-sendiri, catatan HR yang selama ini ditulis di Excel, staf yang bertugas di lokasi lain. Hasil hitungan SeeGaji dibandingkan baris per baris dengan slip yang sudah dibayar.</p>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
              {[["2", "mesin, satu Rekap"], ["±30", "karyawan per periode"], ["0", "rumus Excel yang perlu dirawat"], ["1:1", "dicocokkan dengan slip lama"]].map(([n, l], i) => (
                <div key={l} className="lp-neu-in" style={{ borderRadius: 22, padding: 22 }}>
                  <div style={{ fontSize: 34, fontWeight: 800, color: i === 3 ? "#8A5A00" : "#013D5A" }}>{n}</div>
                  <div style={{ color: "#2E4555", marginTop: 4 }}>{l}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ============ SOON + WHO ============ */}
      <section className="lp-sec-bot">
        <div className="lp-wrap">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 24 }}>
            <div className="lp-soon">
              <div aria-hidden="true" style={{ position: "absolute", right: -60, top: -60, width: 220, height: 220, borderRadius: "50%", background: "rgba(255,255,255,.25)" }} />
              <span className="lp-soon-tag">SEGERA HADIR</span>
              <div className="lp-rel" style={{ fontSize: 30, fontWeight: 800, marginTop: 20, lineHeight: 1.2 }}>BPJS &amp; PPh 21</div>
              <p className="lp-rel" style={{ marginTop: 12, fontSize: 17, lineHeight: 1.6 }}>Iuran BPJS Ketenagakerjaan dan Kesehatan, serta PPh 21 tiap karyawan, dihitung langsung dari payroll yang sama. Disusun bersama konsultan pajak.</p>
            </div>
            <div className="lp-neu" style={{ borderRadius: 28, padding: 36 }}>
              <div className="lp-eyebrow">UNTUK SIAPA</div>
              <div style={{ fontSize: 28, fontWeight: 800, color: "#013D5A", marginTop: 10, lineHeight: 1.2 }}>Usaha apa pun yang menggaji orang.</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 22 }}>
                <div className="lp-who"><i className="lp-neu-in"><svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#013D5A" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 20h20M4 20V10l5 3V10l5 3V6h6v14" /></svg></i><span><b>Kontraktor &amp; pabrik</b>, dengan banyak mesin fingerprint</span></div>
                <div className="lp-who"><i className="lp-neu-in"><svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#013D5A" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="7" y="2" width="10" height="20" rx="2" /><path d="M11 18h2" /></svg></i><span><b>Tim lapangan</b>, absen lewat HP di lokasi kerja</span></div>
                <div className="lp-who"><i className="lp-neu-in"><svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#013D5A" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9h18l-2-5H5L3 9zM5 9v11h14V9" /><path d="M10 20v-6h4v6" /></svg></i><span><b>Toko, kantor &amp; usaha jasa</b>, tanpa mesin pun bisa</span></div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ============ PRICING ============ */}
      <section id="harga" className="lp-sec-tail">
        <div className="lp-wrap">
          <div className="lp-neu lp-dkcb-story" style={{ borderRadius: 36, padding: 48, display: "flex", flexWrap: "wrap", gap: 32, alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ maxWidth: 640 }}>
              <div className="lp-eyebrow">HARGA</div>
              <div className="lp-h2" style={{ fontSize: "clamp(30px, 4vw, 40px)" }}>Hubungi kami.</div>
              <p className="lp-lead" style={{ marginTop: 14 }}>Harga mengikuti jumlah karyawan dan kebutuhan perusahaan Anda. Ceritakan sedikit tentang usaha Anda, kami siapkan demo dengan contoh data seperti milik Anda.</p>
            </div>
            <a className="lp-btn lp-btn-dark lp-btn-lg" href={WA} target="_blank" rel="noopener noreferrer"><WaIcon />Tanya harga via WhatsApp</a>
          </div>
        </div>
      </section>

      {/* ============ FAQ ============ */}
      <section id="faq" className="lp-sec-tail">
        <div className="lp-wrap lp-narrow">
          <div className="lp-eyebrow">PERTANYAAN</div>
          <h2 className="lp-h2">Yang biasanya ditanyakan HR.</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 36 }}>
            {FAQS.map(([q, a], i) => (
              <div key={q} className="lp-neu" style={{ borderRadius: 22 }}>
                <button type="button" className="lp-faq-q" aria-expanded={faq === i} onClick={() => setFaq(faq === i ? -1 : i)}>
                  <span>{q}</span><span className="lp-faq-sign" aria-hidden="true">{faq === i ? "−" : "+"}</span>
                </button>
                {faq === i && <p className="lp-faq-a">{a}</p>}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============ FINAL CTA ============ */}
      <section className="lp-dark lp-dark-cta">
        <Kawung id="kw-cta" />
        <div className="lp-lamp lp-glow" aria-hidden="true" style={{ left: "50%", top: -260, width: 700, height: 520, marginLeft: -350 }} />
        <div className="lp-wrap lp-rel lp-sec" style={{ textAlign: "center" }}>
          <h2 className="lp-h2 lp-h2-light" style={{ margin: "0 auto", maxWidth: 820, fontSize: "clamp(32px, 5vw, 52px)", lineHeight: 1.08 }}>Akhir bulan berikutnya, biar <span className="lp-gold">SeeGaji</span> yang menghitung.</h2>
          <p className="lp-lead lp-lead-dark" style={{ margin: "20px auto 0", maxWidth: 620 }}>Kirim pesan, kami tunjukkan SeeGaji dengan contoh dari usaha Anda sendiri. 30 menit cukup.</p>
          <div className="lp-row" style={{ justifyContent: "center", marginTop: 36 }}>
            <a className="lp-btn lp-btn-gold lp-btn-lg" href={WA} target="_blank" rel="noopener noreferrer">Jadwalkan demo via WhatsApp</a>
            <Link className="lp-btn lp-btn-ghost lp-btn-lg" href={app}>{appHref ? "Buka SeeGaji" : "Masuk ke SeeGaji"}</Link>
          </div>
        </div>
      </section>

      {/* ============ FOOTER ============ */}
      <footer className="lp-foot">
        <div className="lp-wrap lp-foot-in">
          <div className="lp-row" style={{ gap: 12 }}>
            <LogoMark size={32} onDark />
            <span style={{ fontSize: 20, fontWeight: 800, color: "#FFFFFF" }}>See<span className="lp-gold">Gaji</span></span>
            <span>adalah produk dari <a href="https://langit.co.id" style={{ color: "#FFFFFF", fontWeight: 700 }}>Langit</a></span>
          </div>
          <div className="lp-row" style={{ gap: 24 }}>
            <a href="#fitur">Fitur</a><a href="#harga">Harga</a>
            <a href={WA} target="_blank" rel="noopener noreferrer">WhatsApp</a>
            <Link href={app}>{appLabel}</Link>
          </div>
          <div>© 2026 Langit · langit.co.id</div>
        </div>
      </footer>
    </div>
  );
}
