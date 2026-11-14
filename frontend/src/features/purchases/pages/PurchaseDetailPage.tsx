import { useParams } from "react-router-dom";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { PurchaseReview } from "../components/PurchaseReview";
export function PurchaseDetailPage() {
  const { proposalId, approvalId } = useParams();
  const flow = usePurchaseDetail({ proposalId, approvalId });
  return <PurchaseReview flow={flow} />;
}
