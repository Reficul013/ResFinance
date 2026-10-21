import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";

import { currentMonth } from "../finance/money";
import { useInsightsOverview } from "./useInsightsDashboard";

export function NotificationCenter({ accessToken }: { accessToken: string }) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const overview = useInsightsOverview(accessToken, currentMonth());
  const notifications = overview.data?.notifications ?? [];
  const notificationLabel =
    notifications.length === 0
      ? "No in-app notifications"
      : `${notifications.length} in-app notifications`;

  useEffect(() => {
    function closeOnOutsidePointer(event: PointerEvent) {
      const details = detailsRef.current;
      if (
        details?.open &&
        event.target instanceof Node &&
        !details.contains(event.target)
      ) {
        details.open = false;
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      const details = detailsRef.current;
      if (event.key === "Escape" && details?.open) {
        details.open = false;
        details.querySelector("summary")?.focus();
      }
    }

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  function closeNotifications() {
    if (detailsRef.current) detailsRef.current.open = false;
  }

  return (
    <details className="notification-center" ref={detailsRef}>
      <summary aria-label={notificationLabel}>
        <svg
          className="notification-bell"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {notifications.length > 0 && <strong>{notifications.length}</strong>}
      </summary>
      <div className="notification-popover">
        <p className="section-kicker">In-app notifications</p>
        {overview.isPending && (
          <p className="notification-empty">Checking notifications…</p>
        )}
        {overview.isError && (
          <p className="notification-empty">
            Notifications are temporarily unavailable.
          </p>
        )}
        {overview.data !== undefined && notifications.length === 0 && (
          <p className="notification-empty">You’re all caught up.</p>
        )}
        {notifications.slice(0, 5).map((item) => (
          <Link
            to={
              item.href === "/insights" ? "/finance#smart-insights" : item.href
            }
            key={item.notification_id}
            className={`notification-item ${item.severity}`}
            onClick={closeNotifications}
          >
            <strong>{item.title}</strong>
            <span>{item.message}</span>
          </Link>
        ))}
      </div>
    </details>
  );
}
