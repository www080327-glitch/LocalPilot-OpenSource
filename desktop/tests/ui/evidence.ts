import { join } from "node:path";
const run = process.env.LP_UI_EVIDENCE_DIR || `docs/evidence/runs/${new Date().toISOString().replaceAll(":", "-")}-${process.pid}`;
export const evidence = (name: string) => join(run, name);
