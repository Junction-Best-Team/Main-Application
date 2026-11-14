import { Link } from "react-router-dom";
import { currency, dateTime } from "../../../shared/lib/format";
import { placedAt } from "../../purchases/model/acceptedOrders";
import { useAcceptedOrders } from "../../purchases/hooks/useAcceptedOrders";
import { useAuth } from "../../auth/useAuth";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { Icon, InertButton } from "../../../shared/components/DesignPrimitives";

const statusTone: Record<string, string> = {
  Shipping: "bg-status-fresh-green/30 text-primary",
  "Needs Approval": "bg-error-container text-on-error-container",
  Confirmed: "bg-surface-container-highest text-primary",
};

const rowClass =
  "group flex items-center justify-between gap-space-sm rounded-lg bg-surface-container-low p-space-sm no-underline";

export function HomePage() {
  const { session } = useAuth();
  const { orders, error, loading } = useAcceptedOrders(3);
  const m = MOCK.home;
  return (
    <main className="mx-auto flex w-full max-w-7xl flex-col gap-space-lg px-margin-sm py-space-lg md:gap-space-xl md:px-margin md:py-space-xl">
      <div className="flex flex-col gap-space-xs">
        <h1 className="m-0 font-headline text-headline-lg-mobile tracking-normal text-primary md:text-headline-lg">
          Welcome, {session?.buyer_id}
        </h1>
        <p className="m-0 max-w-2xl font-body text-body-md text-on-surface-variant">
          {m.intro}
        </p>
      </div>

      <section
        aria-labelledby="home-banner"
        className="relative flex flex-col justify-between gap-space-lg overflow-hidden rounded-xl bg-primary-container p-space-lg text-on-primary shadow-level-2 lg:flex-row lg:items-center"
      >
        <div className="relative z-10 flex max-w-2xl flex-col gap-space-xs">
          <h2
            id="home-banner"
            className="m-0 font-headline text-headline-md text-text-on-dark"
          >
            Make a New Order in Seconds
          </h2>
          <p className="m-0 font-body text-body-md text-on-primary-container">
            {m.bannerText}
          </p>
        </div>
        <Link
          to="/request"
          className="relative z-10 inline-flex shrink-0 items-center justify-center gap-space-xs self-start rounded-lg bg-status-fresh-green px-space-lg py-3 font-label text-label-lg text-deep-ocean-navy no-underline hover:bg-tertiary-fixed"
        >
          <Icon name="add_shopping_cart" className="text-[20px]" />
          <span>Start Restock Request</span>
          <Icon name="arrow_forward" className="text-[18px]" />
        </Link>
        <Icon
          name="local_shipping"
          className="pointer-events-none absolute -bottom-10 -right-8 text-[240px] text-surface-pure opacity-10"
        />
      </section>

      <div className="grid grid-cols-1 gap-space-lg lg:grid-cols-2">
        <section
          aria-labelledby="home-schedule"
          className="flex flex-col gap-space-sm rounded-xl bg-surface-pure p-space-lg shadow-level-2"
        >
          <div className="flex items-center justify-between gap-space-sm">
            <h3
              id="home-schedule"
              className="m-0 flex items-center gap-space-xs font-headline text-headline-sm text-primary"
            >
              <Icon name="calendar_clock" className="text-wholesale-teal" />
              Active Delivery Schedule · Placeholder
            </h3>
            <InertButton
              label={m.scheduleViewAll}
              className="font-label text-label-md text-wholesale-teal"
            >
              {m.scheduleViewAll}
            </InertButton>
          </div>
          <ul className="m-0 flex list-none flex-col gap-space-xs p-0">
            {m.schedules.map((s) => (
              <li key={s.title}>
                <InertButton label={s.title} className="block w-full text-left">
                  <span className={rowClass}>
                    <span className="flex min-w-0 items-start gap-space-sm">
                      <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary-container text-on-secondary-container">
                        <Icon name={s.icon} className="text-[20px]" />
                      </span>
                      <span className="flex min-w-0 flex-col">
                        <span className="truncate font-label text-label-lg text-deep-ocean-navy">
                          {s.title}
                        </span>
                        <span className="font-label text-label-sm text-secondary">
                          {s.cadence} •{" "}
                          <span className="font-semibold text-on-surface">
                            {s.next}
                          </span>
                        </span>
                      </span>
                    </span>
                    <span className="flex shrink-0 flex-col items-end gap-1">
                      <span
                        className={`rounded px-2 py-0.5 font-label text-label-sm font-semibold ${statusTone[s.status] ?? ""}`}
                      >
                        {s.status}
                      </span>
                      <span className="font-label text-label-md font-bold text-deep-ocean-navy">
                        {s.total}
                      </span>
                    </span>
                  </span>
                </InertButton>
              </li>
            ))}
          </ul>
        </section>

        <section
          aria-labelledby="home-recent"
          className="flex flex-col gap-space-sm rounded-xl bg-surface-pure p-space-lg shadow-level-2"
        >
          <div className="flex items-center justify-between gap-space-sm">
            <h3
              id="home-recent"
              className="m-0 flex items-center gap-space-xs font-headline text-headline-sm text-primary"
            >
              <Icon name="receipt_long" className="text-wholesale-teal" />
              Recent Past Orders
            </h3>
            <Link
              to="/purchases"
              className="inline-flex items-center gap-1 font-label text-label-md text-wholesale-teal no-underline hover:text-deep-ocean-navy"
            >
              View All Past Orders
              <Icon name="arrow_forward" className="text-[16px]" />
            </Link>
          </div>
          {error && (
            <div
              role="alert"
              className="rounded-lg bg-error-container p-space-md text-on-error-container"
            >
              {error}
            </div>
          )}
          {loading && !error && (
            <p role="status" className="m-0 text-secondary">
              Loading past orders…
            </p>
          )}
          {orders?.length === 0 && (
            <p className="m-0 text-secondary">
              No past orders yet. Orders you approve in a request will appear
              here.
            </p>
          )}
          <ul className="m-0 flex list-none flex-col gap-space-xs p-0">
            {orders?.map((p) => (
              <li key={p.proposal_id}>
                <Link
                  to={`/purchases/${p.proposal_id}`}
                  className={`${rowClass} hover:bg-surface-container`}
                >
                  <span className="flex min-w-0 items-start gap-space-sm">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-surface-container-high text-wholesale-teal">
                      <Icon name="check_circle" className="text-[20px]" />
                    </span>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-label text-label-lg text-deep-ocean-navy">
                        {p.request.request_id}
                      </span>
                      <span className="font-label text-label-sm text-on-surface-variant">
                        Accepted (demo) • {dateTime(placedAt(p))}
                      </span>
                    </span>
                  </span>
                  <span className="flex shrink-0 flex-col items-end">
                    <span className="font-headline text-headline-sm font-bold leading-tight text-primary">
                      {currency(p.snapshot.gross_total)}
                    </span>
                    <span className="font-label text-label-sm text-secondary">
                      {p.snapshot.lines.length}{" "}
                      {p.snapshot.lines.length === 1 ? "item" : "items"}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
