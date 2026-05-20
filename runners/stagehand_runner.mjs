import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i];
    const value = argv[i + 1];
    if (key === '--input') out.input = value;
    if (key === '--output') out.output = value;
  }
  if (!out.input || !out.output) {
    throw new Error('Expected --input and --output');
  }
  return out;
}

async function main() {
  const args = parseArgs(process.argv);
  const input = JSON.parse(await readFile(resolve(args.input), 'utf8'));
  let reason = 'missing-package:@browserbasehq/stagehand';
  try {
    await import('@browserbasehq/stagehand');
    reason = 'runner-skeleton-only';
  } catch {}
  const payload = {
    framework: 'stagehand',
    status: 'unavailable',
    notes: [],
    risk_events: [reason],
    metrics: {
      elapsed_ms: 0,
      retry_count: 0,
      crash_count: 0,
      manual_interventions: 0,
      token_cost: 0,
    },
    runner: 'runners/stagehand_runner.mjs',
    input_keyword: input?.task?.keyword ?? '',
  };
  await writeFile(resolve(args.output), JSON.stringify(payload, null, 2), 'utf8');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
