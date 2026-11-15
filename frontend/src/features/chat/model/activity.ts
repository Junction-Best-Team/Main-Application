import type { Conversation } from "../../../shared/api/types";

/** The worker saved reviewed progress after an interruption. */
export function isPartialActivity(activity: Conversation["activity"]) {
  return (
    activity?.state === "complete" &&
    activity.events?.some((event) => event.kind === "error")
  );
}
