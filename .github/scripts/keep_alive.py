"""Open the Streamlit app in a headless browser so it doesn't go to sleep.

A plain HTTP request isn't enough: Streamlit Community Cloud only counts a
visit when a browser opens the app. If the app is already asleep, this clicks
the wake-up button and waits for it to start.
"""

import os
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

WAKE_BUTTON = "Yes, get this app back up!"


def main() -> int:
    url = os.environ.get("APP_URL", "").strip()
    if not url.startswith("https://"):
        print("Set the STREAMLIT_APP_URL repository variable to the app's https URL.")
        return 1

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)

        wake = page.get_by_role("button", name=WAKE_BUTTON)
        try:
            wake.wait_for(state="visible", timeout=15_000)
        except PlaywrightTimeout:
            print("App is awake. Staying briefly so the visit registers.")
            page.wait_for_timeout(30_000)
        else:
            print("App was asleep. Waking it up.")
            wake.click()
            # Starting a sleeping app takes a minute or two.
            page.wait_for_timeout(120_000)

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
