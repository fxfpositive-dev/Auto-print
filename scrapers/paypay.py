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
_HEADER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "date": ("利用日", "日付", "利用年月日", "取引日", "ご利用日"),
    "merchant": ("利用店名", "加盟店名", "店舗名", "お店", "利用先"),
    "amount": ("利用金額", "金額", "支払金額", "ご利用金額", "請求額"),
    "note": ("備考", "摘要", "メモ", "備考欄"),
}


@dataclass
class PaypayCredentials:
    login_id: str
    password: str


@dataclass
class PaypayScraperConfig:
    login_url: str = DEFAULT_LOGIN_URL
    statement_url: str = DEFAULT_STATEMENT_URL
    session_file: Path = Path("data/sessions/paypay.json")
    headless: bool = True
    allow_manual_login: bool = True
    login_timeout_seconds: int = 300
    auto_detect_columns: bool = True
    login_user_selectors: list[str] = field(
        default_factory=lambda: [
            "input[name='loginId']",
            "input[name='userId']",
            "input[name='username']",
            "input[name='memberId']",
            "input[type='email']",
            "input[type='text']",
        ]
    )
    login_password_selectors: list[str] = field(
        default_factory=lambda: ["input[type='password']"]
    )
    login_submit_selectors: list[str] = field(
        default_factory=lambda: ["button[type='submit']", "input[type='submit']"]
    )
    statement_ready_selector: str = "table"
    statement_header_selector: str = "table thead th, table thead td"
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
        self,
        credentials: PaypayCredentials | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[StatementEntry]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.config.headless)
            context = self._create_context(browser)
            try:
                page = context.new_page()
                self._open_statement_page(page, credentials)
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

    def _open_statement_page(
        self, page: Page, credentials: PaypayCredentials | None
    ) -> None:
        page.goto(self.config.statement_url, wait_until="domcontentloaded")
        if self._login_required(page):
            self._handle_login(page, credentials)
        self._wait_for_statement_ready(page)

    def _login_required(self, page: Page) -> bool:
        if "login" in page.url.lower():
            return True
        return page.locator(self.config.login_indicator_selector).count() > 0

    def _handle_login(
        self, page: Page, credentials: PaypayCredentials | None
    ) -> None:
        page.goto(self.config.login_url, wait_until="domcontentloaded")
        if credentials:
            self._fill_login_form(page, credentials)
            self._submit_login_form(page)
            page.goto(self.config.statement_url, wait_until="domcontentloaded")
            self._wait_for_statement_ready(page)
            return

        if not self.config.allow_manual_login:
            raise RuntimeError(
                "Login required; manual login disabled in configuration."
            )
        if self.config.headless:
            raise RuntimeError(
                "Login required; run with headless=False to complete login."
            )
        page.goto(self.config.statement_url, wait_until="domcontentloaded")
        self._wait_for_statement_ready(page)

    def _wait_for_statement_ready(self, page: Page) -> None:
        try:
            page.wait_for_selector(
                self.config.statement_ready_selector,
                timeout=self.config.login_timeout_seconds * 1000,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Statement page did not load in time.") from exc

    def _fill_login_form(self, page: Page, credentials: PaypayCredentials) -> None:
        user_input = _find_first_visible(page, self.config.login_user_selectors)
        password_input = _find_first_visible(page, self.config.login_password_selectors)
        if not user_input or not password_input:
            raise RuntimeError("Login form inputs not found.")
        user_input.fill(credentials.login_id)
        password_input.fill(credentials.password)

    def _submit_login_form(self, page: Page) -> None:
        if _click_first_visible(page, self.config.login_submit_selectors):
            return
        password_input = _find_first_visible(page, self.config.login_password_selectors)
        if not password_input:
            raise RuntimeError("Unable to submit login form.")
        password_input.press("Enter")

    def _extract_entries(self, page: Page) -> list[StatementEntry]:
        rows = page.locator(self.config.statement_row_selector)
        indices = self._resolve_column_indices(page)
        entries: list[StatementEntry] = []
        for row_index in range(rows.count()):
            cells = (
                rows.nth(row_index)
                .locator(self.config.statement_cell_selector)
                .all_text_contents()
            )
            if not cells:
                continue
            entries.append(self._parse_row(cells, row_index, indices))
        return entries

    def _resolve_column_indices(self, page: Page) -> dict[str, int]:
        indices = dict(self.config.column_indices)
        if not self.config.auto_detect_columns:
            return indices
        headers = self._extract_headers(page)
        if not headers:
            return indices
        resolved: dict[str, int] = {}
        for key, keywords in _HEADER_KEYWORDS.items():
            for idx, header in enumerate(headers):
                normalized = header.strip()
                if any(keyword in normalized for keyword in keywords):
                    resolved[key] = idx
                    break
        if resolved:
            indices.update(resolved)
        return indices

    def _extract_headers(self, page: Page) -> list[str]:
        header_locator = page.locator(self.config.statement_header_selector)
        headers = [text.strip() for text in header_locator.all_text_contents()]
        if headers:
            return headers
        first_row = page.locator(self.config.statement_row_selector).first
        if first_row.count() == 0:
            return []
        cells = first_row.locator("th, td").all_text_contents()
        return [text.strip() for text in cells]

    def _parse_row(
        self, cells: list[str], row_index: int, indices: dict[str, int]
    ) -> StatementEntry:
        try:
            raw_date = _safe_cell(cells, indices.get("date"))
            raw_merchant = _safe_cell(cells, indices.get("merchant"))
            raw_amount = _safe_cell(cells, indices.get("amount"))
            raw_note = _safe_cell(cells, indices.get("note"))
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


def _safe_cell(cells: list[str], index: int | None) -> str:
    if index is None:
        return ""
    if index < 0 or index >= len(cells):
        return ""
    return cells[index].strip()


def _find_first_visible(page: Page, selectors: Iterable[str]):
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        element = locator.first
        try:
            if element.is_visible():
                return element
        except PlaywrightTimeoutError:
            continue
    return None


def _click_first_visible(page: Page, selectors: Iterable[str]) -> bool:
    element = _find_first_visible(page, selectors)
    if not element:
        return False
    element.click()
    return True
