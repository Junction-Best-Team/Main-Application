"""Read-only enrichment from active imported Valio datasets; no embeddings or supplier calls."""

from decimal import Decimal

from aimo.schemas import SupplierMetrics

DATASETS = ("delivery_reliability", "carbon_footprint")


def load(c, product_ids):
    ids = list(dict.fromkeys(product_ids))
    if not ids:
        return {}
    metrics = {pid: SupplierMetrics().model_dump(mode="json") for pid in ids}
    rows = c.execute(
        """SELECT a.dataset,a.sha256,p.product_id,v.value
        FROM active_supplier_datasets a CROSS JOIN unnest(%s::text[]) p(product_id)
        LEFT JOIN supplier_dataset_values v
        ON v.dataset=a.dataset AND v.sha256=a.sha256 AND v.product_id=p.product_id
        WHERE a.dataset=ANY(%s)""",
        (ids, list(DATASETS)),
    ).fetchall()
    for row in rows:
        metrics[row["product_id"]][row["dataset"]]["dataset_sha256"] = row["sha256"]
        if row["value"] is None:
            continue
        value = Decimal(row["value"])
        if not value.is_finite() or value < 0:
            continue
        if row["dataset"] == "delivery_reliability" and value > 1:
            continue
        metrics[row["product_id"]][row["dataset"]]["value"] = str(value)
    return metrics


def prefer(ids, metrics, sort_by):
    """Stable tie breaking retains relevance; missing values never become best/zero."""
    if sort_by == "relevance":
        return ids
    dataset = "carbon_footprint" if sort_by == "lower_carbon" else "delivery_reliability"

    def key(pid):
        value = metrics[pid][dataset]["value"]
        return (
            value is None,
            0 if value is None else Decimal(value) * (1 if dataset == "carbon_footprint" else -1),
        )

    return sorted(ids, key=key)
