from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from scrapers.paypay import PaypayCredentials, PaypayScraper, PaypayScraperConfig

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")


@dataclass
class UIState:
    headless: bool = False
    output_dir: Path = Path("data/output")


class PaypayUI:
    def __init__(self, root: tk.Tk, state: UIState | None = None) -> None:
        self.root = root
        self.state = state or UIState()
        self.root.title("Paypay Card Statement")
        self.root.geometry("720x520")

        self.login_id_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.start_date_var = tk.StringVar()
        self.end_date_var = tk.StringVar()
        self.headless_var = tk.BooleanVar(value=self.state.headless)
        self.status_var = tk.StringVar(value="Ready.")

        self._build_layout()

    def _build_layout(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        credentials_frame = ttk.LabelFrame(main, text="Credentials", padding=12)
        credentials_frame.pack(fill=tk.X)

        ttk.Label(credentials_frame, text="Login ID").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(credentials_frame, textvariable=self.login_id_var, width=32).grid(
            row=0, column=1, sticky=tk.W, padx=8, pady=4
        )

        ttk.Label(credentials_frame, text="Password").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(
            credentials_frame,
            textvariable=self.password_var,
            width=32,
            show="*",
        ).grid(row=1, column=1, sticky=tk.W, padx=8, pady=4)

        date_frame = ttk.LabelFrame(main, text="Date Range (optional)", padding=12)
        date_frame.pack(fill=tk.X, pady=12)

        ttk.Label(date_frame, text="Start (YYYY-MM-DD)").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Entry(date_frame, textvariable=self.start_date_var, width=16).grid(
            row=0, column=1, sticky=tk.W, padx=8, pady=4
        )

        ttk.Label(date_frame, text="End (YYYY-MM-DD)").grid(
            row=0, column=2, sticky=tk.W, padx=(16, 0)
        )
        ttk.Entry(date_frame, textvariable=self.end_date_var, width=16).grid(
            row=0, column=3, sticky=tk.W, padx=8, pady=4
        )

        options_frame = ttk.Frame(main)
        options_frame.pack(fill=tk.X)
        ttk.Checkbutton(
            options_frame,
            text="Headless browser",
            variable=self.headless_var,
        ).pack(anchor=tk.W)

        action_frame = ttk.Frame(main)
        action_frame.pack(fill=tk.X, pady=8)

        self.fetch_button = ttk.Button(
            action_frame, text="Fetch Statements", command=self.on_fetch
        )
        self.fetch_button.pack(side=tk.LEFT)
        ttk.Label(action_frame, textvariable=self.status_var).pack(
            side=tk.LEFT, padx=12
        )

        results_frame = ttk.LabelFrame(main, text="Results", padding=8)
        results_frame.pack(fill=tk.BOTH, expand=True, pady=8)

        self.output_text = tk.Text(results_frame, height=12, wrap=tk.NONE)
        self.output_text.pack(fill=tk.BOTH, expand=True)

    def on_fetch(self) -> None:
        login_id = self.login_id_var.get().strip()
        password = self.password_var.get().strip()
        if not login_id or not password:
            messagebox.showerror("Missing input", "Login ID and password are required.")
            return

        try:
            start_date = _parse_optional_date(self.start_date_var.get().strip())
            end_date = _parse_optional_date(self.end_date_var.get().strip())
        except ValueError as exc:
            messagebox.showerror("Invalid date", str(exc))
            return

        credentials = PaypayCredentials(login_id=login_id, password=password)
        self.fetch_button.configure(state=tk.DISABLED)
        self.status_var.set("Fetching statements...")
        self.output_text.delete("1.0", tk.END)

        thread = threading.Thread(
            target=self._run_fetch, args=(credentials, start_date, end_date), daemon=True
        )
        thread.start()

    def _run_fetch(
        self,
        credentials: PaypayCredentials,
        start_date: date | None,
        end_date: date | None,
    ) -> None:
        try:
            config = PaypayScraperConfig(headless=self.headless_var.get())
            scraper = PaypayScraper(config)
            entries = scraper.fetch_statements(
                credentials=credentials, start_date=start_date, end_date=end_date
            )
            output_path = self._save_entries(entries)
            self._notify_success(entries, output_path)
        except Exception as exc:  # noqa: BLE001 - show UI error
            self._notify_error(str(exc))

    def _save_entries(self, entries) -> Path:
        self.state.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = self.state.output_dir / f"paypay-statements-{timestamp}.json"
        payload = [entry.model_dump() for entry in entries]
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return output_path

    def _notify_success(self, entries, output_path: Path) -> None:
        def update() -> None:
            self.status_var.set(f"Fetched {len(entries)} entries.")
            self.fetch_button.configure(state=tk.NORMAL)
            self.password_var.set("")
            self.output_text.insert(
                tk.END,
                f"Saved to: {output_path}\n\n",
            )
            for entry in entries:
                self.output_text.insert(
                    tk.END,
                    f"{entry.date} | {entry.merchant} | {entry.amount} | {entry.note or ''}\n",
                )

        self.root.after(0, update)

    def _notify_error(self, message: str) -> None:
        def update() -> None:
            self.status_var.set("Failed.")
            self.fetch_button.configure(state=tk.NORMAL)
            messagebox.showerror("Fetch failed", message)

        self.root.after(0, update)


def _parse_optional_date(value: str) -> date | None:
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")


def main() -> None:
    root = tk.Tk()
    PaypayUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
