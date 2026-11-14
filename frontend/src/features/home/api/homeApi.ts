import { api } from "../../../shared/api/client";
import type { ScheduleList } from "../../../shared/api/types";

// The card shows only the first few standing orders (newest first); the full list has its own page.
export const listRecentSchedules = (limit = 3) =>
  api<ScheduleList>(`/api/schedules?offset=0&limit=${limit}`);
