#!/usr/bin/env python3
"""
Deep dive into Utility Billing section of BSA Online
"""

import asyncio
import json
import os
from playwright.async_api import async_playwright

os.makedirs("screenshots", exist_ok=True)
os.makedirs("discovery_results", exist_ok=True)

BASE_URL = "https://bsaonline.com"
MUNICIPALITY_UID = "305"

async def discover_utility():
    api_calls = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Capture API calls
        async def log_request(request):
            url = request.url
            if any(x in url.lower() for x in ['search', 'api', 'service', 'query', 'get', 'payment', 'billing', 'utility', 'account']):
                entry = {
                    "url": url,
                    "method": request.method,
                    "post_data": request.post_data
                }
                api_calls.append(entry)
                print(f"[REQUEST] {request.method} {url[:100]}")

        async def log_response(response):
            url = response.url
            if 'search' in url.lower() or 'api' in url.lower() or 'payment' in url.lower():
                try:
                    ct = response.headers.get('content-type', '')
                    if 'json' in ct or 'html' in ct:
                        print(f"[RESPONSE] {response.status} {url[:80]}")
                except:
                    pass

        page.on("request", log_request)
        page.on("response", log_response)

        # Go directly to Utility Billing Payments search
        print("\n=== Loading Utility Billing Search ===\n")
        url = f"{BASE_URL}/OnlinePayment/OnlinePaymentSearch?PaymentApplicationType=10&uid={MUNICIPALITY_UID}"
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        await page.screenshot(path="screenshots/utility_billing_search.png", full_page=True)
        print("Screenshot: screenshots/utility_billing_search.png")

        # Analyze the page
        title = await page.title()
        print(f"Page title: {title}")
        print(f"URL: {page.url}")

        # Find all forms
        print("\n=== Forms on Utility Billing Page ===")
        forms = await page.query_selector_all("form")
        for i, form in enumerate(forms):
            form_id = await form.get_attribute("id") or "no-id"
            action = await form.get_attribute("action") or "no action"
            method = await form.get_attribute("method") or "GET"
            print(f"\nForm {i+1} (id={form_id}): {method} -> {action}")

            # Get all inputs
            inputs = await form.query_selector_all("input, select, textarea")
            for inp in inputs:
                tag = await inp.evaluate("el => el.tagName")
                name = await inp.get_attribute("name") or await inp.get_attribute("id") or "unnamed"
                inp_type = await inp.get_attribute("type") or "text"
                value = await inp.get_attribute("value") or ""
                placeholder = await inp.get_attribute("placeholder") or ""

                if tag == "SELECT":
                    # Get select options
                    options = await inp.query_selector_all("option")
                    opt_texts = []
                    for opt in options[:5]:  # First 5 options
                        opt_text = await opt.inner_text()
                        opt_value = await opt.get_attribute("value")
                        opt_texts.append(f"{opt_value}:{opt_text[:20]}")
                    print(f"  SELECT {name}: [{', '.join(opt_texts)}]")
                else:
                    print(f"  {inp_type.upper()} {name} = '{value}' ({placeholder})")

        # Look for search buttons
        print("\n=== Buttons ===")
        buttons = await page.query_selector_all("button, input[type='submit'], input[type='button'], a.btn")
        for btn in buttons:
            text = await btn.inner_text() if await btn.evaluate("el => el.tagName") != "INPUT" else await btn.get_attribute("value")
            onclick = await btn.get_attribute("onclick") or ""
            print(f"  Button: '{text}' onclick={onclick[:50]}")

        # Look for tabs or sections
        print("\n=== Tabs/Search Options ===")
        tabs = await page.query_selector_all("[class*='tab'], [role='tab'], .nav-link, .search-option")
        for tab in tabs:
            text = (await tab.inner_text()).strip()[:40]
            if text:
                print(f"  Tab: {text}")

        # Try to find specific search fields
        print("\n=== Looking for search fields ===")
        search_selectors = [
            ('Account Number', 'input[name*="account" i], input[id*="account" i], input[placeholder*="account" i]'),
            ('Address', 'input[name*="address" i], input[id*="address" i], input[placeholder*="address" i]'),
            ('Name', 'input[name*="name" i], input[id*="name" i], input[placeholder*="name" i]'),
            ('Parcel', 'input[name*="parcel" i], input[id*="parcel" i]'),
        ]

        for label, selector in search_selectors:
            elements = await page.query_selector_all(selector)
            for el in elements:
                name = await el.get_attribute("name") or await el.get_attribute("id")
                if name:
                    print(f"  {label}: found input '{name}'")

        # Try a test search if we find the right fields
        print("\n=== Testing Search Functionality ===")

        # Look for the main search input
        search_input = await page.query_selector('input[name="SearchText"], input[id="SearchText"], input[type="text"]:visible')
        if search_input:
            print("Found search input, testing with sample address...")

            # Enter a test search
            await search_input.fill("123")  # Simple test
            await asyncio.sleep(1)

            # Look for search button
            search_btn = await page.query_selector('input[type="submit"], button[type="submit"], button:has-text("Search")')
            if search_btn:
                print("Clicking search...")
                await search_btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await asyncio.sleep(2)

                await page.screenshot(path="screenshots/utility_search_results.png", full_page=True)
                print("Screenshot: screenshots/utility_search_results.png")

                # Check results
                results_url = page.url
                print(f"Results URL: {results_url}")

                # Look for result items
                results = await page.query_selector_all("table tr, .result-item, .search-result, [class*='result']")
                print(f"Found {len(results)} potential result rows")

                # Get table headers if present
                headers = await page.query_selector_all("table th, thead td")
                if headers:
                    header_texts = [await h.inner_text() for h in headers]
                    print(f"Table headers: {header_texts}")

        # Get the page HTML for detailed analysis
        html = await page.content()
        with open("discovery_results/utility_page.html", "w") as f:
            f.write(html)

        await browser.close()

    # Save API calls
    with open("discovery_results/utility_api_calls.json", "w") as f:
        json.dump(api_calls, f, indent=2)

    print(f"\n=== Saved {len(api_calls)} API calls ===")

    return api_calls

if __name__ == "__main__":
    asyncio.run(discover_utility())
