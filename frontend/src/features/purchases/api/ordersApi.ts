import { api } from "../../../shared/api/client";
import type { Cancellation, OrdersResponse } from "../../../shared/api/types";

export const listOrders = (offset = 0, limit = 20) =>
  api<OrdersResponse>(`/api/orders?offset=${offset}&limit=${limit}`);
// Cancels a pending order REQUEST (not a standing order). 409 ORDER_ALREADY_PLACED once ordered.
export const cancelRequest = (csrf: string, proposalId: string) =>
  api<Cancellation>(`/api/purchases/${proposalId}/cancel`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrf },
  });
