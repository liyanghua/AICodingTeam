# Taobao Collector

Independent manual-login Taobao mobile image collector.

This v1 collector uses public mobile UI automation only. It does not automate
login, captcha, payment, cart, order, private APIs, or anti-bot bypass.

## Commands

From this package directory:

```bash
cd third_party/taobao_collector

python -m taobao_collector calibrate \
  --output config/taobao_coordinates.json

python -m taobao_collector run \
  --dry-run \
  --mode keyword_search \
  --keyword "red plaid table mat" \
  --top-n 3

python -m taobao_collector run \
  --mode image_search \
  --input-image path/to/reference.jpg \
  --top-n 10

python -m taobao_collector run \
  --mode keyword_search \
  --keyword "red plaid table mat" \
  --top-n 10

python -m taobao_collector run \
  --mode both \
  --input-image path/to/reference.jpg \
  --keywords keywords.txt \
  --top-n 10
```

## Output

Each run writes:

- `manifest.json`
- `step_events.jsonl`
- `results.csv`
- `results.html`
- `images/`
- `debug/`

The manifest includes `channel=taobao`, `mode`, `query`, `stage`, `rank`,
`source_item_id`, and `content_sha256` so later material-center ingestion can
dedupe by category and content hash.

## Safety

The collector stops on login, captcha, verification, cart, order, or payment
prompts. It keeps debug screenshots/XML and records a risk event instead of
continuing.

## Keyword Search Spec

See `docs/keyword_search_collection_spec.md` for the keyword-search collection
contract, page-state gates, event names, and regression cases. Use that spec
before changing the keyword flow or turning it into a reusable skill.
