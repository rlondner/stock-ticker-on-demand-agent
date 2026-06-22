// Active only when SENTRY_DSN_NEXTJS is set. Initialization is handled by the
// sentry.{server,client,edge}.config.ts files at framework boot — this module
// is a marker for explicit readability of the exporters/ directory.
export const sentryEnabled = !!process.env.SENTRY_DSN_NEXTJS;
