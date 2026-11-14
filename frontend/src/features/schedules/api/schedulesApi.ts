import { api } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";
import type {
  Schedule,
  ScheduleDetail,
  ScheduleList,
  ScheduleTerms,
  SubstituteCandidates,
} from "../../../shared/api/types";

type Schemas = components["schemas"];
const write = (csrf: string, body?: unknown): RequestInit => ({
  method: "POST",
  headers: { "X-CSRF-Token": csrf },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

export const listSchedules = (offset = 0) =>
  api<ScheduleList>(`/api/schedules?offset=${offset}&limit=20`);
export const getSchedule = (id: string, runsOffset = 0) =>
  api<ScheduleDetail>(`/api/schedules/${id}?runs_offset=${runsOffset}`);
export const substituteCandidates = (productId: string) =>
  api<SubstituteCandidates>(
    `/api/schedules/substitute-candidates?product_id=${encodeURIComponent(productId)}`,
  );
export const previewNewSchedule = (
  csrf: string,
  body: Schemas["SchedulePreviewRequest"],
) => api<ScheduleTerms>("/api/schedules/preview", write(csrf, body));
export const createSchedule = (
  csrf: string,
  body: Schemas["ScheduleCreateRequest"],
) => api<Schedule>("/api/schedules", write(csrf, body));
export const previewScheduleEdit = (
  csrf: string,
  id: string,
  body: Schemas["ScheduleEditPreviewRequest"],
) => api<ScheduleTerms>(`/api/schedules/${id}/preview`, write(csrf, body));
export const replaceSchedule = (
  csrf: string,
  id: string,
  body: Schemas["ScheduleReplaceRequest"],
) => api<Schedule>(`/api/schedules/${id}/replace`, write(csrf, body));
export const cancelSchedule = (csrf: string, id: string) =>
  api<Schedule>(`/api/schedules/${id}/cancel`, write(csrf));
export const pauseSchedule = (csrf: string, id: string) =>
  api<Schedule>(`/api/schedules/${id}/pause`, write(csrf));
export const resumeSchedule = (csrf: string, id: string) =>
  api<Schedule>(`/api/schedules/${id}/resume`, write(csrf));
