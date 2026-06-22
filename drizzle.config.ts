import type { Config } from "drizzle-kit";

export default {
  schema: "./lib/db/schema.ts",
  out: "./db/migrations-drizzle",
  dialect: "postgresql",
  dbCredentials: { url: process.env.NEON_DATABASE_URL! },
} satisfies Config;
