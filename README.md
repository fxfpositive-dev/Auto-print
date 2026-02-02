# Auto-print

Card statement auto-printing skeleton.

## Proposed structure

```
.
├── config.yaml
├── data/                 # sessions, generated PDFs (local)
├── scrapers/             # per-provider scrapers
├── templates/            # Jinja2 HTML/CSS templates
└── src/                  # shared models and utilities
```

## Config sample (config.yaml)

```yaml
app:
  data_dir: "data"
  session_dir: "data/sessions"
  output_dir: "data/output"

scrapers:
  providers:
    - "paypay"
    - "aeon"
    - "view"
  paypay:
    login_url: "https://www.paypay-card.co.jp/"
    statement_url: "https://www.paypay-card.co.jp/"
    session_file: "data/sessions/paypay.json"
    headless: true
    allow_manual_login: true

templates:
  statement_html: "templates/statement.html"
  stylesheet: "templates/style.css"

printing:
  enabled: true
  command: "lp"
  options:
    - "-o"
    - "fit-to-page"
```

## Paypay scraper (skeleton)

```python
from datetime import date

from scrapers.paypay import PaypayScraper, PaypayScraperConfig

config = PaypayScraperConfig(headless=False)
scraper = PaypayScraper(config)
entries = scraper.fetch_statements(start_date=date(2024, 1, 1))
```
