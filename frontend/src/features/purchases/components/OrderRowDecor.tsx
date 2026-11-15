import { useId, useLayoutEffect, useRef, useState } from "react";
import { random, TOOLS } from "../../../shared/lib/kitchenTools";

// EXPLORATION: a barely visible pattern in the empty part of an order row (desktop). Rows
// rotate through the versions (row index % 3) so they can be compared; keep one and delete
// the rest once chosen.
//   0 · scattered shapes (squares, triangles, circles) whose outlines are wavy lines
//   1 · scattered kitchen tools (whisk, spoon, fork, knife, spatula, ladle, rolling pin,
//       frying pan, pot) drawn as outlines
// The area follows the empty space: it starts after the status row's last item (the date),
// then swings left in an S-curve underneath it, beside the shorter title and line count, and
// stops short of the right-hand column. Measured from the row's own elements (data-decor
// attributes in OrderRow), so it adapts to each row. Decorative only: hidden from assistive
// tech, in the text colour at a few percent opacity.

export const ORDER_DECOR_VARIANTS = 2;

type Area = {
  width: number;
  height: number;
  /** Left edge in the top band (after the status row) and below it (after the text). */
  topX: number;
  bottomX: number;
  /** Where the S-curve runs, vertically. */
  curveFrom: number;
  curveTo: number;
  /** Bottom of the text (below it the edge can curve back out). */
  textBottom: number; // kept for tuning the curve's lower end
  /** Right edge (before the right-hand column). */
  rightX: number;
  /** Right edge beside the (short) date at the top, and where the right-side S ends. */
  rightTopX: number;
  rightCurveTo: number;
};

const textLeft = (el: Element | null, origin: number) => {
  if (!el || !el.textContent?.trim()) return Infinity;
  const range = document.createRange();
  range.selectNodeContents(el);
  return range.getBoundingClientRect().left - origin;
};

const textRight = (el: Element | null, origin: number) => {
  if (!el) return 0;
  const range = document.createRange();
  range.selectNodeContents(el);
  return range.getBoundingClientRect().right - origin;
};

function measure(header: HTMLElement, bleedBottom: boolean): Area {
  const box = header.getBoundingClientRect();
  const meta = header.querySelector<HTMLElement>('[data-decor="meta"]');
  const right = header.querySelector<HTMLElement>('[data-decor="right"]');
  const metaEnd = meta?.lastElementChild
    ? meta.lastElementChild.getBoundingClientRect().right - box.left
    : 0;
  const textEnd = Math.max(
    textRight(header.querySelector('[data-decor="title"]'), box.left),
    textRight(header.querySelector('[data-decor="lines"]'), box.left),
  );
  const metaBottom = meta ? meta.getBoundingClientRect().bottom - box.top : 26;
  const lines = header.querySelector('[data-decor="lines"]');
  const textBottom = lines
    ? lines.getBoundingClientRect().bottom - box.top
    : box.height;
  // Right side: beside the short date at the top, before the wider total and buttons below.
  const columnLeft = right
    ? right.getBoundingClientRect().left - box.left
    : box.width;
  const when = header.querySelector('[data-decor="when"]');
  const actions = header.querySelector('[data-decor="actions"]');
  const firstAction = actions?.firstElementChild;
  const rightTop = Math.min(box.width, textLeft(when, box.left)) - 26;
  const rightBottom =
    Math.min(
      columnLeft + 400,
      textLeft(header.querySelector('[data-decor="total"]'), box.left),
      firstAction
        ? firstAction.getBoundingClientRect().left - box.left
        : Infinity,
    ) - 26;
  const whenBottom = when ? when.getBoundingClientRect().bottom - box.top : 26;
  // Room for the soft edge (FADE) to finish before the text.
  const topX = metaEnd + 26;
  const bottomX = textEnd + 34;
  return {
    width: box.width,
    height: box.height + PAD + (bleedBottom ? PAD : 0),
    topX,
    bottomX,
    curveFrom: PAD + metaBottom,
    // Swinging left (under the date) the S uses everything below the status row; swinging
    // right it must finish before the title starts.
    curveTo:
      bottomX < topX
        ? box.height + PAD + (bleedBottom ? PAD : 0)
        : PAD + metaBottom + 2,
    textBottom: PAD + textBottom,
    rightX: rightBottom,
    rightTopX: Math.max(rightBottom, rightTop),
    rightCurveTo: PAD + whenBottom,
  };
}

/** How softly the area fades out at its edges (blur radius of its mask), px. */
const FADE = 9;
const ROUND = 40; // how far the edge curves in at the top, px
const START_ANGLE = (30 * Math.PI) / 180; // the S leaves the left side at 30°
const easeOut = (t: number) =>
  Math.sin((Math.min(1, Math.max(0, t)) * Math.PI) / 2);
const smooth = (t: number) => {
  const c = Math.min(1, Math.max(0, t));
  return c * c * (3 - 2 * c);
};

/** Points along the S as a cubic Bézier: it leaves the lower-left point rising at
 *  START_ANGLE, bends, and arrives heading straight up into the status row's edge. */
function sCurve(a: Area): [number, number][] {
  const span = a.curveTo - a.curveFrom;
  const run = a.topX - a.bottomX;
  const lead = Math.min(run * 0.6, (span * 0.9) / Math.sin(START_ANGLE));
  const p0: [number, number] = [a.bottomX, a.curveTo];
  const p1: [number, number] = [
    a.bottomX + lead * Math.cos(START_ANGLE),
    a.curveTo - lead * Math.sin(START_ANGLE),
  ];
  const p2: [number, number] = [a.topX, a.curveFrom + span * 0.45];
  const p3: [number, number] = [a.topX, a.curveFrom];
  return Array.from({ length: 61 }, (_, i) => {
    const t = i / 60;
    const u = 1 - t;
    const at = (k: 0 | 1) =>
      u * u * u * p0[k] +
      3 * u * u * t * p1[k] +
      3 * u * t * t * p2[k] +
      t * t * t * p3[k];
    return [at(0), at(1)];
  });
}

const curves = new WeakMap<Area, [number, number][]>();

/** The left edge at height y: rounds in from the top edge, follows the status row, then
 *  bends down along the S to the lower left. Never crosses the text. */
function leftAt(a: Area, y: number) {
  if (y < PAD) return a.topX + ROUND * (1 - easeOut(y / PAD));
  if (y <= a.curveFrom) return a.topX;
  if (a.bottomX >= a.topX) {
    // Title wider than the status row: a short step right before the title.
    if (y >= a.curveTo) return a.bottomX;
    return (
      a.topX +
      (a.bottomX - a.topX) *
        smooth((y - a.curveFrom) / (a.curveTo - a.curveFrom))
    );
  }
  if (y >= a.curveTo) return a.bottomX;
  let points = curves.get(a);
  if (!points) {
    points = sCurve(a);
    curves.set(a, points);
  }
  // The curve runs from the bottom (index 0) up to the status row; find y on it.
  for (let i = 1; i < points.length; i++) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    if (y <= y0 && y >= y1) {
      const t = y0 === y1 ? 0 : (y0 - y) / (y0 - y1);
      return x0 + (x1 - x0) * t;
    }
  }
  return a.bottomX;
}

/** The right edge at height y: straight beside the total and buttons, then (above the date's
 *  bottom) an S that leaves at START_ANGLE and arrives heading straight up beside the date,
 *  mirroring the left side. */
const rightCurves = new WeakMap<Area, [number, number][]>();
function rightAt(a: Area, y: number) {
  if (y >= a.rightCurveTo || a.rightTopX <= a.rightX) return a.rightX;
  let points = rightCurves.get(a);
  if (!points) {
    const span = a.rightCurveTo;
    const run = a.rightTopX - a.rightX;
    const lead = Math.min(run * 0.6, (span * 0.9) / Math.sin(START_ANGLE));
    const p0: [number, number] = [a.rightX, a.rightCurveTo];
    const p1: [number, number] = [
      a.rightX + lead * Math.cos(START_ANGLE),
      a.rightCurveTo - lead * Math.sin(START_ANGLE),
    ];
    const p2: [number, number] = [a.rightTopX, span * 0.45];
    const p3: [number, number] = [a.rightTopX, 0];
    points = Array.from({ length: 41 }, (_, i) => {
      const t = i / 40;
      const u = 1 - t;
      const at = (k: 0 | 1) =>
        u * u * u * p0[k] +
        3 * u * u * t * p1[k] +
        3 * u * t * t * p2[k] +
        t * t * t * p3[k];
      return [at(0), at(1)] as [number, number];
    });
    rightCurves.set(a, points);
  }
  for (let i = 1; i < points.length; i++) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    if (y <= y0 && y >= y1) {
      const t = y0 === y1 ? 0 : (y0 - y) / (y0 - y1);
      return x0 + (x1 - x0) * t;
    }
  }
  return a.rightTopX;
}

/** The region as an SVG path: the curved left edge down, the curved right edge back up. */
function regionPath(a: Area) {
  const points: string[] = [];
  for (let y = 0; y <= a.height; y += 2)
    points.push(`${leftAt(a, y).toFixed(1)} ${y}`);
  points.push(`${leftAt(a, a.height).toFixed(1)} ${a.height}`);
  for (let y = a.height; y >= 0; y -= 2)
    points.push(`${rightAt(a, y).toFixed(1)} ${y}`);
  points.push(`${rightAt(a, 0).toFixed(1)} 0`);
  return `M ${points.join(" L ")} Z`;
}

const AMP = 0.8; // wave height of the outlines, px
const WAVELENGTH = 11;
/** The row's padding (md:p-space-lg): the drawing runs over it to the card's edges, where
 *  the card cuts it off. */
const PAD = 24;

/** A closed outline through `points`, every edge drawn as a wave. */
function wavyPolygon(points: [number, number][]) {
  let d = "";
  points.forEach(([x0, y0], i) => {
    const [x1, y1] = points[(i + 1) % points.length];
    const length = Math.hypot(x1 - x0, y1 - y0);
    const nx = -(y1 - y0) / length;
    const ny = (x1 - x0) / length;
    const steps = Math.max(4, Math.round(length / 1.5));
    for (let s = 0; s <= steps; s++) {
      const t = s / steps;
      const off = AMP * Math.sin((2 * Math.PI * t * length) / WAVELENGTH);
      const x = x0 + (x1 - x0) * t + nx * off;
      const y = y0 + (y1 - y0) * t + ny * off;
      d += `${d ? " L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    }
  });
  return `${d} Z`;
}

function wavyCircle(cx: number, cy: number, r: number) {
  const waves = Math.max(5, Math.round((2 * Math.PI * r) / WAVELENGTH));
  let d = "";
  for (let s = 0; s <= 72; s++) {
    const a = (s / 72) * 2 * Math.PI;
    const rr = r + AMP * Math.sin(waves * a);
    d += `${d ? " L" : "M"} ${(cx + rr * Math.cos(a)).toFixed(1)} ${(cy + rr * Math.sin(a)).toFixed(1)}`;
  }
  return `${d} Z`;
}

function shape(kind: number, cx: number, cy: number, r: number, turn: number) {
  if (kind === 2) return wavyCircle(cx, cy, r * 0.85);
  const corners = kind === 0 ? 4 : 3;
  const points: [number, number][] = Array.from({ length: corners }, (_, i) => {
    const a = turn + (i * 2 * Math.PI) / corners;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  });
  return wavyPolygon(points);
}

/** Randomly scattered shapes inside the area, not overlapping. */
type Spot = { x: number; y: number; r: number; pick: number; turn: number };

/** Random, non-overlapping spots inside the area (they may hang over the card's edges). */
function scatter(a: Area, seed: number) {
  const next = random(seed);
  const placed: Spot[] = [];
  for (let tries = 0; tries < 500 && placed.length < 40; tries++) {
    const r = 13 + next() * 12;
    // May hang over the top and bottom edges; the card cuts those off.
    const y = -r * 0.5 + next() * (a.height + r);
    const left = leftAt(a, y) + r + 2;
    const x = left + next() * Math.max(0, rightAt(a, y) - r - left);
    if (x - r < leftAt(a, y - r) || x - r < leftAt(a, y + r)) continue;
    if (x + r > rightAt(a, y - r) || x + r > rightAt(a, y + r)) continue;
    if (placed.some((p) => Math.hypot(p.x - x, p.y - y) < p.r + r + 12))
      continue;
    placed.push({ x, y, r, pick: next(), turn: next() });
  }
  return placed;
}

/** Stroke opacity of the pattern: always faint. */
const DIM = 0.07;

export function OrderRowDecor({
  variant,
  expanded = false,
}: {
  variant: number;
  /** The row is open: stop at the header instead of running into the details. */
  expanded?: boolean;
}) {
  const id = useId().replace(/:/g, "");
  const svg = useRef<SVGSVGElement>(null);
  const [area, setArea] = useState<Area | null>(null);
  const kind = variant % ORDER_DECOR_VARIANTS;

  useLayoutEffect(() => {
    const header = svg.current?.parentElement;
    if (!header) return;
    const update = () => setArea(measure(header, !expanded));
    const observer = new ResizeObserver(update);
    observer.observe(header);
    update();
    return () => observer.disconnect();
  }, [expanded]);

  const usable = area && area.rightX - Math.min(area.topX, area.bottomX) > 24;
  return (
    <svg
      ref={svg}
      aria-hidden="true"
      // Runs over the row's padding to the card's top (and, when closed, bottom) edge.
      className="pointer-events-none absolute inset-x-0 -z-10 hidden text-primary lg:block"
      style={{ top: -PAD, bottom: expanded ? 0 : -PAD, width: "100%" }}
    >
      {usable && (
        <>
          <defs>
            {/* A blurred mask: the pattern fades out near the text, the right-hand column
                and the card's edges instead of stopping hard. */}
            <filter
              id={`soft-${id}`}
              x="-20%"
              y="-20%"
              width="140%"
              height="140%"
            >
              <feGaussianBlur stdDeviation={FADE} />
            </filter>
            {/* A slight softness on the shapes and tools, so they sit back. */}
            <filter
              id={`blur-${id}`}
              x="-10%"
              y="-10%"
              width="120%"
              height="120%"
            >
              <feGaussianBlur stdDeviation="0.8" />
            </filter>
            <mask
              id={`area-${id}`}
              maskUnits="userSpaceOnUse"
              x="0"
              y="0"
              width={area.width}
              height={area.height}
            >
              <path
                d={regionPath(area)}
                fill="white"
                filter={`url(#soft-${id})`}
              />
            </mask>
          </defs>
          <g mask={`url(#area-${id})`}>
            {kind === 0 ? (
              <g
                fill="none"
                stroke="currentColor"
                strokeWidth="1.3"
                filter={`url(#blur-${id})`}
              >
                {scatter(area, 7919 * (variant + 1)).map((s, i) => (
                  <path
                    key={i}
                    strokeOpacity={DIM}
                    d={shape(
                      Math.floor(s.pick * 3),
                      s.x,
                      s.y,
                      s.r,
                      s.turn * Math.PI,
                    )}
                  />
                ))}
              </g>
            ) : (
              <g
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                filter={`url(#blur-${id})`}
              >
                {scatter(area, 7919 * (variant + 1)).map((s, i) => (
                  <path
                    key={i}
                    d={TOOLS[Math.floor(s.pick * TOOLS.length)]}
                    strokeOpacity={DIM}
                    vectorEffect="non-scaling-stroke"
                    transform={`translate(${s.x.toFixed(1)} ${s.y.toFixed(1)}) rotate(${(s.turn * 360).toFixed(0)}) scale(${((s.r * 2.2) / 48).toFixed(3)}) translate(-24 -24)`}
                  />
                ))}
              </g>
            )}
          </g>
        </>
      )}
    </svg>
  );
}
