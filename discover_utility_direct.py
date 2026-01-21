#!/usr/bin/env python3
"""
Try the direct utility billing search forms
"""

import asyncio
import json
import os
from playwright.async_api import async_playwright

os.makedirs("screenshots", exist_ok=True)

BASE_URL = "https://bsaonline.com"
UID = "305"

async def test_utility_search():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Track responses
        responses_data = []

        async def capture_response(response):
            if 'payment' in response.url.lower() or 'search' in response.url.lower():
                try:
                    content_type = response.headers.get('content-type', '')
                    if 'json' in content_type:
                        data = await response.json()
                        responses_data.append({"url": response.url, "data": data})
                        print(f"[JSON] {response.url[:60]}")
                except:
                    pass

        page.on("response", capture_response)

        # Go to utility billing page
        print("Loading utility billing page...")
        await page.goto(f"{BASE_URL}/OnlinePayment/OnlinePaymentSearch?PaymentApplicationType=10&uid={UID}", wait_until="networkidle")
        await asyncio.sleep(2)

        # Take screenshot
        await page.screenshot(path="screenshots/ub_01_main.png", full_page=True)
        print(f"URL: {page.url}")

        # Look for specific utility search forms (Forms 2 and 3 from discovery)
        print("\n=== Looking for Utility Search Forms ===")

        # Method 1: Try Account Number form directly
        print("\nTrying Account Number search...")
        account_form = await page.query_selector('form[action*="Account%20Number"]')
        if account_form:
            print("Found Account Number form!")
            account_input = await account_form.query_selector('input[name="AccountNumber"]')
            if account_input:
                await account_input.fill("123456")  # Test account
                submit = await account_form.query_selector('input[type="submit"]')
                if submit:
                    await submit.click()
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await asyncio.sleep(2)
                    await page.screenshot(path="screenshots/ub_02_account_search.png", full_page=True)
                    print(f"After account search URL: {page.url}")

                    # Check for results or errors
                    content = await page.content()
                    if "no results" in content.lower() or "not found" in content.lower():
                        print("No results found (expected for test account)")
                    elif "error" in content.lower():
                        print("Error occurred")
                    else:
                        # Look for result tables
                        tables = await page.query_selector_all("table")
                        print(f"Found {len(tables)} tables on results page")

        # Go back and try address search
        await page.goto(f"{BASE_URL}/OnlinePayment/OnlinePaymentSearch?PaymentApplicationType=10&uid={UID}", wait_until="networkidle")
        await asyncio.sleep(1)

        print("\nTrying Address search...")
        address_form = await page.query_selector('form[action*="Address"]')
        if address_form:
            print("Found Address form!")
            address_input = await address_form.query_selector('input[name="Address"]')
            if address_input:
                await address_input.fill("Main")  # Partial address test
                submit = await address_form.query_selector('input[type="submit"]')
                if submit:
                    await submit.click()
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await asyncio.sleep(2)
                    await page.screenshot(path="screenshots/ub_03_address_search.png", full_page=True)
                    print(f"After address search URL: {page.url}")

                    # Analyze results page
                    content = await page.content()

                    # Look for result elements
                    results = await page.query_selector_all("table tr, .payment-result, [class*='result']")
                    print(f"Found {len(results)} potential results")

                    # Get table headers
                    headers = await page.query_selector_all("table th")
                    if headers:
                        header_texts = []
                        for h in headers:
                            text = await h.inner_text()
                            header_texts.append(text.strip())
                        print(f"Table headers: {header_texts}")

                    # Get first few rows
                    rows = await page.query_selector_all("table tbody tr")
                    print(f"Data rows: {len(rows)}")
                    for i, row in enumerate(rows[:3]):
                        cells = await row.query_selector_all("td")
                        cell_texts = []
                        for cell in cells:
                            text = await cell.inner_text()
                            cell_texts.append(text.strip()[:30])
                        print(f"  Row {i+1}: {cell_texts}")

                    # Look for links to detail pages
                    detail_links = await page.query_selector_all('a[href*="Payment"], a[href*="Detail"], a[href*="Account"]')
                    for link in detail_links[:3]:
                        href = await link.get_attribute("href")
                        text = await link.inner_text()
                        print(f"  Link: {text[:30]} -> {href[:60] if href else 'no href'}")

        # Save final HTML
        html = await page.content()
        with open("discovery_results/utility_results_page.html", "w") as f:
            f.write(html)

        await browser.close()

        # Save captured responses
        if responses_data:
            with open("discovery_results/utility_responses.json", "w") as f:
                json.dump(responses_data, f, indent=2)
            print(f"\nSaved {len(responses_data)} JSON responses")

if __name__ == "__main__":
    asyncio.run(test_utility_search())
