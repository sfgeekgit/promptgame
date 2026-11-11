// Draws Zipperlip. He gets older every level: more beard, more hat, more stars.
// Everything is plain SVG built from a few numbers, so there are no image files.

const WIZARD_LOOKS = [
  // hat, robe, beard colour, beard length (0 = none), brow colour, extras
  { hat: "#2fbf71", robe: "#27a05f", beard: null,      len: 0,   brow: "#7a4a21", hair: "#8b5a2b" },
  { hat: "#2f9be6", robe: "#2580c4", beard: "#8b5a2b", len: 26,  brow: "#7a4a21", hair: "#8b5a2b" },
  { hat: "#f08a24", robe: "#d47416", beard: "#7a4a21", len: 70,  brow: "#6b3f1b", hair: "#7a4a21", moustache: true },
  { hat: "#e5484d", robe: "#c2373c", beard: "#c9cad6", len: 120, brow: "#b9bac8", hair: "#c9cad6", moustache: true, staff: true, wrinkles: true },
  { hat: "#8e4ec6", robe: "#7a3db3", beard: "#e4e4ee", len: 150, brow: "#dcdce8", hair: "#e4e4ee", moustache: true, staff: true, wrinkles: true, glasses: true },
  { hat: "#d6409f", robe: "#b8338a", beard: "#efeff6", len: 175, brow: "#efeff6", hair: "#efeff6", moustache: true, staff: true, wrinkles: true, glasses: true },
  { hat: "#12a594", robe: "#0e8a7b", beard: "#f6f6fb", len: 200, brow: "#f6f6fb", hair: "#f6f6fb", moustache: true, staff: true, wrinkles: true, glasses: true },
  { hat: "#f5b800", robe: "#d99e00", beard: "#ffffff", len: 228, brow: "#ffffff", hair: "#ffffff", moustache: true, staff: true, wrinkles: true, glasses: true, glow: true },
];

function wizardSVG(stage, mood) {
  const L = WIZARD_LOOKS[Math.max(0, Math.min(WIZARD_LOOKS.length - 1, stage - 1))];
  const ink = "#1b1340";
  const skin = "#f8cfa6";
  const hatTop = 40 - stage * 3;            // the hat grows a little each level
  const stars = [];
  const spots = [[150, 78], [128, 104], [170, 112], [143, 132], [118, 138], [178, 140], [158, 96], [136, 60]];
  for (let i = 0; i < Math.min(spots.length, stage); i++) {
    const [x, y] = spots[i];
    stars.push(`<path d="M${x} ${y - 7} l2.2 4.6 5 .7 -3.6 3.5 .9 5 -4.5 -2.4 -4.5 2.4 .9 -5 -3.6 -3.5 5 -.7z" fill="#fff6b0" stroke="${ink}" stroke-width="1.5" stroke-linejoin="round"/>`);
  }

  // Eyes and mouth change with his mood.
  let eyes, mouth;
  if (mood === "shock") {
    eyes = `<circle cx="128" cy="190" r="11" fill="#fff" stroke="${ink}" stroke-width="3"/><circle cx="172" cy="190" r="11" fill="#fff" stroke="${ink}" stroke-width="3"/>
            <circle cx="128" cy="190" r="4" fill="${ink}"/><circle cx="172" cy="190" r="4" fill="${ink}"/>`;
    mouth = `<ellipse cx="150" cy="226" rx="9" ry="12" fill="#7a1f2b" stroke="${ink}" stroke-width="3"/>`;
  } else if (mood === "smug") {
    eyes = `<path d="M118 192 q10 -9 20 0" fill="none" stroke="${ink}" stroke-width="4" stroke-linecap="round"/>
            <path d="M162 192 q10 -9 20 0" fill="none" stroke="${ink}" stroke-width="4" stroke-linecap="round"/>`;
    mouth = `<path d="M136 222 q16 10 30 -4" fill="none" stroke="${ink}" stroke-width="4" stroke-linecap="round"/>`;
  } else {
    eyes = `<g class="wz-eyes"><ellipse cx="128" cy="190" rx="6" ry="8" fill="${ink}"/><ellipse cx="172" cy="190" rx="6" ry="8" fill="${ink}"/>
            <circle cx="130" cy="187" r="2" fill="#fff"/><circle cx="174" cy="187" r="2" fill="#fff"/></g>`;
    mouth = `<path class="wz-mouth" d="M134 220 q16 14 32 0" fill="#7a1f2b" stroke="${ink}" stroke-width="3" stroke-linejoin="round"/>`;
  }

  const beardBottom = 232 + L.len;
  const beard = L.beard
    ? `<path d="M98 205 Q92 ${232 + L.len * 0.55} ${150 - Math.min(34, L.len * 0.2)} ${beardBottom - 8} Q150 ${beardBottom + 14} ${150 + Math.min(34, L.len * 0.2)} ${beardBottom - 8} Q208 ${232 + L.len * 0.55} 202 205 Q176 236 150 236 Q124 236 98 205z"
         fill="${L.beard}" stroke="${ink}" stroke-width="4" stroke-linejoin="round"/>`
    : "";
  const moustache = L.moustache
    ? `<path d="M150 212 q-14 -10 -34 4 q18 10 34 2 q16 8 34 -2 q-20 -14 -34 -4z" fill="${L.beard}" stroke="${ink}" stroke-width="3" stroke-linejoin="round"/>`
    : "";
  const freckles = stage === 1
    ? `<g fill="#d99a6c"><circle cx="118" cy="208" r="2.2"/><circle cx="126" cy="213" r="2.2"/><circle cx="174" cy="213" r="2.2"/><circle cx="182" cy="208" r="2.2"/></g>`
    : "";
  const wrinkles = L.wrinkles
    ? `<g fill="none" stroke="#d8a67c" stroke-width="2.5" stroke-linecap="round"><path d="M112 198 q-6 3 -8 8"/><path d="M188 198 q6 3 8 8"/><path d="M132 166 h36"/></g>`
    : "";
  const glasses = L.glasses
    ? `<g fill="rgba(255,255,255,.35)" stroke="${ink}" stroke-width="3"><circle cx="128" cy="190" r="15"/><circle cx="172" cy="190" r="15"/><path d="M143 190 h14" fill="none"/></g>`
    : "";
  const staff = L.staff
    ? `<g><rect x="243" y="150" width="9" height="200" rx="4" fill="#8b5a2b" stroke="${ink}" stroke-width="3"/>
         <circle class="wz-orb" cx="247.5" cy="138" r="${13 + stage}" fill="${L.glow ? "#fff3a6" : "#9be7ff"}" stroke="${ink}" stroke-width="3"/></g>`
    : "";
  const glow = L.glow ? `<circle cx="150" cy="200" r="150" fill="url(#wzGlow)"/>` : "";
  const hair = `<path d="M96 176 q-10 20 -4 40 q6 -14 12 -22z M204 176 q10 20 4 40 q-6 -14 -12 -22z" fill="${L.hair}" stroke="${ink}" stroke-width="3" stroke-linejoin="round"/>`;

  return `<svg viewBox="0 0 300 ${Math.max(360, beardBottom + 30)}" preserveAspectRatio="xMidYMin meet" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Zipperlip the wizard">
    <defs><radialGradient id="wzGlow"><stop offset="0" stop-color="#fff3a6" stop-opacity=".55"/><stop offset="1" stop-color="#fff3a6" stop-opacity="0"/></radialGradient></defs>
    ${glow}
    ${staff}
    <path d="M70 360 Q76 262 112 240 L188 240 Q224 262 230 360z" fill="${L.robe}" stroke="${ink}" stroke-width="4" stroke-linejoin="round"/>
    ${hair}
    <circle cx="150" cy="196" r="56" fill="${skin}" stroke="${ink}" stroke-width="4"/>
    ${wrinkles}
    <path d="M150 ${hatTop} Q${196 + stage * 2} ${hatTop + 20} 176 ${hatTop + 34} L214 156 L86 156z" fill="${L.hat}" stroke="${ink}" stroke-width="4" stroke-linejoin="round"/>
    <ellipse cx="150" cy="156" rx="${82 + stage * 2}" ry="15" fill="${L.hat}" stroke="${ink}" stroke-width="4"/>
    ${stars.join("")}
    <path d="M114 174 q14 -9 28 -2" fill="none" stroke="${L.brow}" stroke-width="${4 + stage * 0.7}" stroke-linecap="round"/>
    <path d="M158 172 q14 -7 28 2" fill="none" stroke="${L.brow}" stroke-width="${4 + stage * 0.7}" stroke-linecap="round"/>
    ${eyes}
    ${glasses}
    ${freckles}
    ${beard}
    <ellipse cx="150" cy="206" rx="8" ry="6" fill="#eeb07f" stroke="${ink}" stroke-width="2.5"/>
    ${mouth}
    ${moustache}
  </svg>`;
}
