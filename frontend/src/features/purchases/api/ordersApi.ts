import { api } from "../../../shared/api/client";
import type { Cancellation, OrdersResponse } from "../../../shared/api/types";

// `status` is a status or a comma list of them (scheduled, pending, placed, cancelled); the
// server filters and `total` counts every matching row.
export const listOrders = (
  offset = 0,
  limit = 20,
  status?: string,
  q?: string,
) =>
  api<OrdersResponse>(
    `/api/orders?offset=${offset}&limit=${limit}${status ? `&status=${encodeURIComponent(status)}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
  );
// Cancels a pending order REQUEST (not a standing order). 409 ORDER_ALREADY_PLACED once ordered.
export const cancelRequest = (csrf: string, proposalId: string) =>
  api<Cancellation>(`/api/purchases/${proposalId}/cancel`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrf },
  });
