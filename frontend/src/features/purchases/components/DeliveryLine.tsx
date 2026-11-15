import type { Proposal } from "../../../shared/api/types";
import { deliveryLine } from "../model/cardState";

/** The delivery in one line, with Edit (opens the Delivery tab) while it can still be changed. */
export function DeliveryLine({
  p,
  editable,
  onEdit,
}: {
  p: Proposal;
  editable: boolean;
  onEdit: () => void;
}) {
  return (
    <p
      data-testid="card-delivery-line"
      className="m-0 flex items-center justify-between gap-space-sm py-1 font-label text-label-md text-primary"
    >
      <span className="min-w-0 break-words">{deliveryLine(p)}</span>
      {editable && (
        <button
          type="button"
          aria-label="Edit delivery"
          onClick={onEdit}
          className="cursor-pointer border-0 bg-transparent p-0 font-label text-label-md font-bold text-wholesale-teal underline"
        >
          Edit
        </button>
      )}
    </p>
  );
}
