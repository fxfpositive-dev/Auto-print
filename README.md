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
