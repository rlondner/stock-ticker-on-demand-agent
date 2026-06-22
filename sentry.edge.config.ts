import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN_NEXTJS;
if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: 1.0,
  });
}
