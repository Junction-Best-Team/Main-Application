import { useLayoutEffect, useRef, useState } from "react";
import { random, toolTransform, TOOLS } from "../lib/kitchenTools";

// A faint background of scattered kitchen tool outlines for a whole page (the schedule
// pages). One tool per cell of a jittered grid keeps them evenly spread but random-looking;
// the seed keeps the layout stable between renders. Decorative: hidden from assistive tech,
// very low contrast, slightly soft, and pinned behind the page's content area (right of the
// desktop sidebar) while the page scrolls over it. The parent needs `isolate`.

const CELL = 120;

export function KitchenPattern({
  seed = 1,
  avoid,
}: {
  seed?: number;
  /** CSS selector of a top-left element (e.g. a page heading) to keep clear: the pattern is
   *  cut away around it along a soft Bézier curve. */
  avoid?: string;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [clear, setClear] = useState<{ w: number; h: number } | null>(null);
  useLayoutEffect(() => {
    const update = () => {
      setSize({ width: window.innerWidth, height: window.innerHeight });
      const target = avoid ? document.querySelector(avoid) : null;
      const origin = svg.current?.getBoundingClientRect();
      if (!target || !origin) return setClear(null);
      const box = target.getBoundingClientRect();
      // Big enough that the curve passes outside the element's far corner.
      setClear({
        w: (box.right - origin.left) * 1.35 + 24,
        h: (box.bottom - origin.top) * 1.35 + 24,
      });
    };
    const observer = new ResizeObserver(update);
    const target = avoid ? document.querySelector(avoid) : null;
    if (target) observer.observe(target);
    window.addEventListener("resize", update);
    update();
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [avoid]);

  const next = random(seed * 104729);
  const tools: string[] = [];
  for (let y = 0; y < size.height + CELL; y += CELL)
    for (let x = 0; x < size.width + CELL; x += CELL) {
      const px = x + next() * CELL * 0.7;
      const py = y + next() * CELL * 0.7;
      const pick = TOOLS[Math.floor(next() * TOOLS.length)];
      tools.push(`${pick}|${toolTransform(px, py, 34 + next() * 18, next())}`);
    }

  return (
    <svg
      ref={svg}
      aria-hidden="true"
      // An SVG needs an explicit size: with only left/right set it falls back to 300px wide.
      // On phones it starts below the app's top bar.
      className="pointer-events-none fixed top-16 left-0 -z-10 h-[calc(100%-4rem)] w-full text-primary md:top-0 md:left-60 md:h-full md:w-[calc(100%-15rem)]"
    >
      <defs>
        {clear && (
          <>
            <filter
              id={`kitchen-edge-${seed}`}
              x="-20%"
              y="-20%"
              width="140%"
              height="140%"
            >
              <feGaussianBlur stdDeviation="10" />
            </filter>
            <mask
              id={`kitchen-clear-${seed}`}
              maskUnits="userSpaceOnUse"
              x="0"
              y="0"
              width={size.width}
              height={size.height}
            >
              <rect width={size.width} height={size.height} fill="white" />
              {/* The cleared corner: a quarter-round Bézier from the top edge to the left
                  edge, bulging out past the element, with a soft edge. */}
              <path
                d={`M -20 -20 H ${clear.w} C ${clear.w} ${clear.h * 0.65} ${clear.w * 0.65} ${clear.h} -20 ${clear.h} Z`}
                fill="black"
                filter={`url(#kitchen-edge-${seed})`}
              />
            </mask>
          </>
        )}
        <filter id="kitchen-soft" x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur stdDeviation="0.8" />
        </filter>
      </defs>
      <g
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.07"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#kitchen-soft)"
        mask={clear ? `url(#kitchen-clear-${seed})` : undefined}
      >
        {tools.map((tool, i) => {
          const [d, transform] = tool.split("|");
          return (
            <path
              key={i}
              d={d}
              transform={transform}
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
      </g>
    </svg>
  );
}
