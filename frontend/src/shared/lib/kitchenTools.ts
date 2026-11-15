// Kitchen tool outlines and a seeded random generator, shared by the decorative patterns
// (order rows, schedule pages).

/** Kitchen tool outlines in a 48 x 48 box centred on (24, 24). */
export const TOOLS = [
  // whisk
  "M24 46 V28 M24 28 C13 22 13 6 24 3 C35 6 35 22 24 28 M24 28 C19 20 19 8 24 3 C29 8 29 20 24 28",
  // spoon
  "M17 11 a7 9 0 1 0 14 0 a7 9 0 1 0 -14 0 M24 20 V46",
  // fork
  "M18 2 V13 M22 2 V13 M26 2 V13 M30 2 V13 M18 13 Q18 20 24 21 Q30 20 30 13 M24 21 V46",
  // knife
  "M21 2 Q33 10 29 28 H21 Z M21 28 H29 V43 Q29 46 26 46 H24 Q21 46 21 43 Z",
  // spatula
  "M16 2 H32 V17 Q32 21 28 21 H20 Q16 21 16 17 Z M21 6 V16 M24 6 V16 M27 6 V16 M24 21 V46",
  // ladle
  "M33 3 Q36 18 30 27 M14 28 H34 A10 9 0 0 1 14 28 Z",
  // rolling pin
  "M10 18 H38 V30 H10 Z M2 22 H10 V26 H2 Z M38 22 H46 V26 H38 Z",
  // frying pan
  "M6 28 a12 12 0 1 0 24 0 a12 12 0 1 0 -24 0 M29 22 L45 12 L47 15 L31 26",
  // pot
  "M8 18 H40 V36 Q40 42 34 42 H14 Q8 42 8 36 Z M5 18 H43 M20 12 H28 M20 12 V18 M28 12 V18 M4 23 H8 M40 23 H44",
];

/** Small seeded random generator, so a row keeps the same scatter between renders. */
export function random(seed: number) {
  let t = seed >>> 0;
  return () => {
    t = (t + 0x6d2b79f5) >>> 0;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

/** SVG transform that draws a 48 x 48 tool centred on (x, y), turned and scaled to `size`. */
export const toolTransform = (
  x: number,
  y: number,
  size: number,
  turn: number,
) =>
  `translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${(turn * 360).toFixed(0)}) scale(${(size / 48).toFixed(3)}) translate(-24 -24)`;
