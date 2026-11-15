// Springs defined the way Apple does (SwiftUI `spring(response:dampingFraction:)`), converted
// to Motion's physical spring for a unit mass:
//   stiffness = (2π / response)²      damping = 4π · dampingFraction / response
// `response` is roughly how long the spring takes to settle (seconds); a damping fraction of
// 1 never overshoots, lower values bounce a little.
export function appleSpring(response: number, dampingFraction: number) {
  return {
    type: "spring" as const,
    mass: 1,
    stiffness: ((2 * Math.PI) / response) ** 2,
    damping: (4 * Math.PI * dampingFraction) / response,
  };
}

/** Large entrances, e.g. a card sliding up from off-screen. */
export const SHEET_SPRING = appleSpring(0.75, 0.9);
/** Small, quick UI movement, e.g. the nav pointer highlight. */
export const SNAPPY_SPRING = appleSpring(0.35, 0.82);
