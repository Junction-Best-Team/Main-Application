const KEY = "aimo.debug";

// Debug mode shows extra support tools (the Copy link on errors). There is no UI to turn it on:
// open any page with ?debug=1 (remembered in this browser) and ?debug=0 to turn it off again.
export function isDebugMode(): boolean {
  try {
    const flag = new URLSearchParams(window.location.search).get("debug");
    if (flag === "1") localStorage.setItem(KEY, "1");
    else if (flag === "0") localStorage.removeItem(KEY);
    if (flag === "0") return false;
    if (flag === "1") return true;
    return localStorage.getItem(KEY) === "1";
  } catch {
    // Storage can throw (blocked site data) or be empty; stay off unless the URL asked for it.
    try {
      return new URLSearchParams(window.location.search).get("debug") === "1";
    } catch {
      return false;
    }
  }
}
