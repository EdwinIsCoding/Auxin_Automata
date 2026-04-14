"use client";

import { useEffect } from "react";

/**
 * Initialises Sentry on the client side when NEXT_PUBLIC_SENTRY_DSN is set.
 * Dynamically imports @sentry/react so it never bundles when DSN is absent.
 */
export function SentryProvider() {
  useEffect(() => {
    const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
    if (!dsn) return;

    import("@sentry/react").then((Sentry) => {
      Sentry.init({
        dsn,
        tracesSampleRate: 0.2,
        environment: process.env.NODE_ENV,
      });
    });
  }, []);

  return null;
}
