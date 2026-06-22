import { neon } from "@neondatabase/serverless";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const dbUrl = process.env.NEON_DATABASE_URL;
if (!dbUrl) {
  console.error("NEON_DATABASE_URL is not set");
  process.exit(1);
}

const sql = neon(dbUrl);
const dir = "db/migrations";
const files = readdirSync(dir).filter((f) => f.endsWith(".sql")).sort();

for (const f of files) {
  console.log(`Applying ${f}...`);
  const stmt = readFileSync(join(dir, f), "utf8");
  // Neon HTTP driver doesn't support multi-statement; split on ;
  for (const part of stmt.split(/;\s*$/m).map(s => s.trim()).filter(Boolean)) {
    await sql.query(part);
  }
}
console.log("Done.");
