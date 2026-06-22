import { pgTable, uuid, text, timestamp, jsonb, index } from "drizzle-orm/pg-core";

export const jobs = pgTable(
  "jobs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: text("user_id").notNull().default("demo-user"),
    ticker: text("ticker").notNull(),
    status: text("status").notNull().default("pending"),
    recommendation: text("recommendation"),
    result: jsonb("result"),
    error: text("error"),
    sandboxId: text("sandbox_id"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    startedAt: timestamp("started_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
  },
  (t) => ({
    userStatusCreatedIdx: index("jobs_user_status_created_idx").on(
      t.userId, t.status, t.createdAt,
    ),
  }),
);

export type Job = typeof jobs.$inferSelect;
export type NewJob = typeof jobs.$inferInsert;
export type JobStatus = "pending" | "running" | "complete" | "failed";
export type Recommendation = "buy" | "hold" | "sell";
