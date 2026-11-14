import { useEffect } from "react";

export function useRefresh(load: () => Promise<void>, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      if (active && document.visibilityState === "visible") await load();
      if (active) timer = setTimeout(tick, 30000);
    }
    timer = setTimeout(tick, 30000);
    const visibility = () => {
      if (document.visibilityState === "visible") {
        clearTimeout(timer);
        void tick();
      }
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      active = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [load, enabled]);
}
