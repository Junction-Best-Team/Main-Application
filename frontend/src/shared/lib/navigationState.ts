// Whether the buyer has moved between pages since this page load. Lets a screen tell a
// refresh or first visit (no entrance animation) from arriving via in-app navigation.
let navigated = false;

export function markNavigated() {
  navigated = true;
}

export function hasNavigated() {
  return navigated;
}
