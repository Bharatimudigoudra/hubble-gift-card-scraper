# Code walkthrough

## Flow

1. `parse_args()` chooses `--practice` (3 brands) or `--full` (100 brands).
2. `HubbleClient.catalog()` requests the catalog in Hubble's returned order.
3. `HubbleClient.brand_sources()` uses each `brandKey` to get the brand record and extra metadata. It uses the returned `externalId` to get terms and redemption data.
4. `transform()` combines those source objects into one consistent brand record.
5. `validate()` checks count, unique keys, duplicates and missing fields.
6. `save_outputs()` writes nested JSON, flattened CSV and a validation report.

## Major functions

### `clean_text()`
Removes repeated whitespace. If source text is missing or blank, it returns `None`. JSON writes that as `null`.

### `unique_nonempty()`
Removes blank and duplicate list entries while preserving the original order.

### `HubbleClient.__init__()`
Creates one reusable HTTP session. It retries connection errors, HTTP 429 and temporary server errors. Backoff makes each retry wait longer.

### `HubbleClient._wait()`
Enforces the delay between requests. The command-line delay can be increased, but code clamps it to a safe minimum of 0.35 seconds.

### `HubbleClient.get_json()`
Makes one GET request. A failed optional endpoint is logged and becomes `None`; it does not invent data.

### `parse_redeem()`
Reads each redemption mode, such as App, Website or Offline, and keeps the step order.

### `validity_text()`
Collects source statements containing “valid” from conditions and FAQs. It also preserves `validityInDays` when the API provides that structured field.

### `flatten()`
Turns lists and nested objects into readable text cells for CSV. JSON remains the richer format for applications.

### `validate()`
For practice mode, the expected count is 3. For full mode, it is 100. It also checks that every `brand_key` is present and unique.

## What you can say in an interview

“I reused the ingestion pattern from my earlier crawler: input, HTTP collection, cleaning, schema mapping, validation, JSON/CSV export and error logging. For Hubble I adapted it to a catalog-plus-detail API. I preserve the catalog order, use each brand key to request detail data, keep missing optional values as null, and fail validation if the expected unique brand count is wrong. I also use retries, backoff and rate limiting so the collector is polite.”
