import { Link } from "react-router-dom";
import { cadenceLabel, formatDate } from "../../schedules/model/scheduleStatus";
import { useStandingOrders } from "../hooks/useStandingOrders";

// The compact strip under the chat box on Home: the next runs of the customer's real standing
// orders (GET /api/schedules). Every order a standing order places is a mock order.
export function StandingOrdersCard() {
  const { schedules, loading, error } = useStandingOrders(3);
  const shown = schedules.slice(0, 3);
  return (
    <section
      className="home-schedule"
      aria-labelledby="home-schedule"
      aria-describedby="home-demo-note"
    >
      <div className="home-schedule-heading">
        <h2 id="home-schedule">Scheduled deliveries</h2>
        <Link to="/schedules">View all</Link>
      </div>
      {error && (
        <p role="alert" className="m-0">
          {error}
        </p>
      )}
      {loading && !error && <p role="status">Loading standing orders…</p>}
      {!loading && !error && shown.length === 0 && (
        <p className="m-0">
          No standing orders yet.{" "}
          <Link to="/purchases">Schedule a past order</Link>
        </p>
      )}
      {shown.length > 0 && (
        <ul>
          {shown.map((s) => (
            <li key={s.id}>
              <time dateTime={s.next_run_date ?? undefined}>
                {s.next_run_date ? formatDate(s.next_run_date) : "Paused"}
              </time>
              <Link to={`/schedules/${s.id}`}>
                {s.title} · {cadenceLabel(s.recurrence)}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
