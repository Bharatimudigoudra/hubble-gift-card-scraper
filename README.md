# Hubble Top-100 Gift-Card Extractor

A small Python project you can read, run and explain. It gets Hubble's current ranked catalog, fetches each brand's public detail data, keeps missing values as `null`, and exports JSON plus CSV.

This is a clean, reproducible reference implementation based on the verified public endpoints. It does **not** claim to be the exact unsaved code from an earlier extraction.

## What each file does

- `hubble_scraper.py` - complete scraper, parser, validation and export code.
- `requirements.txt` - the one Python package to install.
- `run_practice.bat` - Windows shortcut for the first 3 brands.
- `run_full.bat` - Windows shortcut for all 100 brands.
- `output/` - sample live output from practice mode.
- `logs/` - request progress and non-fatal errors.
- `CODE_WALKTHROUGH.md` - major functions explained in plain language.

## Windows instructions for your conda GenAI environment

Open **Anaconda Prompt**. Run these commands one at a time. Do not paste `$` or other prompt characters.

1. Go to the extracted folder. Change the path to where you downloaded it:

```bat
cd /d C:\Users\YourName\Downloads\hubble-gift-card-scraper
```

2. Activate your existing environment:

```bat
conda activate GenAI
```

3. Check Python:

```bat
python --version
```

4. Install the pinned dependency:

```bat
python -m pip install -r requirements.txt
```

5. Run the small 3-brand practice mode first:

```bat
python hubble_scraper.py --practice
```

6. Open the generated files:

```bat
start output
```

7. After practice mode succeeds, run the full ranked 100:

```bat
python hubble_scraper.py --full
```

The full run is intentionally slow because the script waits between requests. Watch progress in the prompt. Outputs are saved in `output`, and the log is saved in `logs`.

## One-click alternatives

After installing requirements, you may double-click `run_practice.bat` or `run_full.bat`. The command-by-command method above is better for learning because you can see each stage.

## Output files

Practice mode creates:

- `output/hubble-gift-cards-practice-3.json`
- `output/hubble-gift-cards-practice-3.csv`
- `output/validation-practice-3.json`

Full mode creates the same three file types with `top100` in the names. JSON preserves nested FAQs and redemption steps. CSV flattens those lists for Excel or Google Sheets.

## How the source is used

Catalog:

`https://api.myhubble.money/v3/store/products/search?q=&limit=100&pageNo=0`

For every returned `brandKey`, the script requests the public brand record and extra metadata. It uses the returned `externalId` for terms and redemption details. The matching user-facing page is kept as `source_url`.

## Validation rules

The run passes only when:

- actual count equals requested count, 3 or 100;
- every record has a brand key;
- all brand keys are unique.

Missing optional fields do not fail the run. They remain `null` and are counted in the validation report. This avoids invented content.

## Safe and ethical use

- Use this only for learning and reasonable personal data preparation.
- The code is deliberately sequential and enforces at least 0.35 seconds between requests.
- It retries temporary errors with backoff and respects `Retry-After` on rate limits.
- Do not remove the delay, add high concurrency, bypass access controls, scrape personal data, or keep hammering the service after errors.
- Hubble can change its API or terms. Stop if access is denied or the service asks clients not to automate.
- Re-check the source before relying on gift-card terms because offers and policies change.

## Common problems

**`conda` is not recognized**: use Anaconda Prompt, not ordinary Command Prompt.

**`ModuleNotFoundError: requests`**: activate `GenAI`, then repeat the pip install command.

**HTTP 429**: the service is rate-limiting. Stop, wait, and retry later. Do not reduce the delay.

**Validation exits with code 2**: open the matching validation JSON and log. The catalog may have changed or a temporary request failed.
