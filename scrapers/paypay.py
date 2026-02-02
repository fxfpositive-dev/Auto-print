from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import re
from typing import Iterable

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from src.schema import StatementEntry

DEFAULT_LOGIN_URL = "https://www.paypay-card.co.jp/"
DEFAULT_STATEMENT_URL = "https://www.paypay-card.co.jp/"

_AMOUNT_CLEAN_RE = re.compile(r"[^\d\-\.,()]+")


@dataclass
class PaypayScraperConfig:
    login_url: str = DEFAULT_LOGIN_URL
    statement_url: str = DEFAULT_STATEMENT_URL
    session_file: Path = Path("data/sessions/paypay.json")
    headless: bool = True
    allow_manual_login: bool = True
    login_timeout_seconds: int = 300
    statement_ready_selector: str = "table"
    statement_row_selector: str = "table tbody tr"
    statement_cell_selector: str = "td"
    login_indicator_selector: str = "input[type='password']"
    column_indices: dict[str, int] = field(
        default_factory=lambda: {
            "date": 0,
            "merchant": 1,
            "amount": 2,
            "note": 3,
        }
    )


class PaypayScraper:
    def __init__(self, config: PaypayScraperConfig | None = None) -> None:
        self.config = config or PaypayScraperConfig()

    def fetch_statements(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> list[StatementEntry]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.config.headless)
            context = self._create_context(browser)
            try:
                page = context.new_page()
                self._open_statement_page(page)
                entries = self._extract_entries(page)
                return self._filter_date_range(entries, start_date, end_date)
            finally:
                self._persist_session(context)
                context.close()
                browser.close()

    def _create_context(self, browser):
        if self.config.session_file.exists():
            return browser.new_context(storage_state=str(self.config.session_file))
        return browser.new_context()

    def _persist_session(self, context) -> None:
        self.config.session_file.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(self.config.session_file))

    def _open_statement_page(self, page: Page) -> None:
        page.goto(self.config.statement_url, wait_until="domcontentloaded")
        if self._login_required(page):
            self._handle_login(page)
        page.wait_for_selector(
            self.config.statement_ready_selector,
            timeout=self.config.login_timeout_seconds * 1000,
        )

    def _login_required(self, page: Page) -> bool:
        if "login" in page.url.lower():
            return True
        return page.locator(self.config.login_indicator_selector).count() > 0

    def _handle_login(self, page: Page) -> None:
        if not self.config.allow_manual_login:
            raise RuntimeError(
                "Login required; manual login disabled in configuration."
            )
        if self.config.headless:
            raise RuntimeError(
                "Login required; run with headless=False to complete login."
            )
        page.goto(self.config.login_url, wait_until="domcontentloaded")
        try:
            page.wait_for_url(
                self.config.statement_url,
                timeout=self.config.login_timeout_seconds * 1000,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Login timed out.") from exc

    def _extract_entries(self, page: Page) -> list[StatementEntry]:
        rows = page.locator(self.config.statement_row_selector)
        entries: list[StatementEntry] = []
        for row_index in range(rows.count()):
            cells = (
                rows.nth(row_index)
                .locator(self.config.statement_cell_selector)
                .all_text_contents()
            )
            if not cells:
                continue
            entries.append(self._parse_row(cells, row_index))
        return entries

    def _parse_row(self, cells: list[str], row_index: int) -> StatementEntry:
        indices = self.config.column_indices
        try:
            raw_date = cells[indices["date"]].strip()
            raw_merchant = cells[indices["merchant"]].strip()
            raw_amount = cells[indices["amount"]].strip()
            raw_note = cells[indices.get("note", -1)].strip() if "note" in indices else ""
            parsed_date = _parse_date(raw_date)
            parsed_amount = _parse_amount(raw_amount)
            note = raw_note or None
            return StatementEntry(
                date=parsed_date,
                merchant=raw_merchant,
                amount=parsed_amount,
                note=note,
            )
        except Exception as exc:  # noqa: BLE001 - provide row detail
            raise ValueError(f"Failed parsing row {row_index}: {cells}") from exc

    def _filter_date_range(
        self,
        entries: Iterable[StatementEntry],
        start_date: date | None,
        end_date: date | None,
    ) -> list[StatementEntry]:
        filtered: list[StatementEntry] = []
        for entry in entries:
            if start_date and entry.date < start_date:
                continue
            if end_date and entry.date > end_date:
                continue
            filtered.append(entry)
        return filtered


def _parse_date(raw: str) -> date:
    raw = raw.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    match = re.match(r"(\d{1,2})[/-](\d{1,2})", raw)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        return date(date.today().year, month, day)
    raise ValueError(f"Unsupported date format: {raw}")


def _parse_amount(raw: str) -> Decimal:
    raw = raw.strip()
    if not raw:
        raise ValueError("Empty amount.")
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = _AMOUNT_CLEAN_RE.sub("", raw)
    cleaned = cleaned.strip("()")
    if cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:]
    cleaned = cleaned.replace(",", "")
    if not cleaned:
        raise ValueError(f"Unsupported amount format: {raw}")
    value = Decimal(cleaned)
    return -value if negative else value
