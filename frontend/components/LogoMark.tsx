// SeeGaji logo mark "Si Mata": the two e's of "See" become two eyes, you can see your pay.
// Light ground: Midnight tile, Marigold eyes. Dark ground (onDark): Marigold tile, white eyes.
// print: black only, for slips. Pure SVG, so it is sharp at 28 px and at 512 px.
export default function LogoMark({ size = 32, onDark = false, print = false }: { size?: number; onDark?: boolean; print?: boolean }) {
  const tile = print ? "#111111" : onDark ? "#F5A623" : "#013D5A";
  const eye = print ? "#FFFFFF" : onDark ? "#FFFFFF" : "#F5A623";
  const pupil = print ? "#111111" : "#013D5A";
  const shine = !print && !onDark;
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" style={{ flexShrink: 0, display: "block" }}>
      <rect width="48" height="48" rx="13" fill={tile} />
      <circle cx="16.5" cy="24" r="8.2" fill={eye} />
      <circle cx="31.5" cy="24" r="8.2" fill={eye} />
      <circle cx="18" cy="23" r="3.7" fill={pupil} />
      <circle cx="33" cy="23" r="3.7" fill={pupil} />
      {shine && <circle cx="19.2" cy="21.7" r="1.1" fill="#FFFFFF" />}
      {shine && <circle cx="34.2" cy="21.7" r="1.1" fill="#FFFFFF" />}
    </svg>
  );
}
