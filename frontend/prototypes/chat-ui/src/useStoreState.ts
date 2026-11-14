import { useSyncExternalStore } from "react";
import { store } from "./store";

export function useStoreState() {
  return useSyncExternalStore(store.subscribe, store.getSnapshot);
}
