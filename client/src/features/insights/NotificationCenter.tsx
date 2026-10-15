import { Link } from "react-router-dom";

import { currentMonth } from "../finance/money";
import { useInsightsOverview } from "./useInsightsDashboard";

export function NotificationCenter({ accessToken }: { accessToken: string }) {
  const overview = useInsightsOverview(accessToken, currentMonth());
  if (!overview.data || overview.data.notifications.length === 0) return null;
  const notifications = overview.data.notifications;
  return (
    <details className="notification-center">
      <summary aria-label={`${notifications.length} in-app notifications`}>
        <span aria-hidden="true">◎</span>
        <strong>{notifications.length}</strong>
      </summary>
      <div className="notification-popover">
        <p className="section-kicker">In-app notifications</p>
        {notifications.slice(0, 5).map((item) => (
          <Link
            to={item.href}
            key={item.notification_id}
            className={`notification-item ${item.severity}`}
          >
            <strong>{item.title}</strong>
            <span>{item.message}</span>
          </Link>
        ))}
        <Link className="notification-all" to="/insights">
          Open Smart Savings Insights
        </Link>
      </div>
    </details>
  );
}
