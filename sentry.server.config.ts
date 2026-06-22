import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN_NEXTJS;
if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: 1.0,
    environment: process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
  });
}
