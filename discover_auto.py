#!/usr/bin/env python3
"""
Automatic BSA Online Discovery - captures page structure and API endpoints
"""

import asyncio
import json
import os
from playwright.async_api import async_playwright

os.makedirs("screenshots", exist_ok=True)
os.makedirs("discovery_results", exist_ok=True)

BASE_URL = "https://bsaonline.com"
MUNICIPALITY_UID = "305"

async def discover():
    requests_log = []
    api_calls = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Capture all requests
        async def log_request(request):
            entry = {
                "url": request.url,
                "method": request.method,
                "type": request.resource_type,
            }
            requests_log.append(entry)

            # Flag potential API calls
            url_lower = request.url.lower()
            if any(x in url_lower for x in ['/api/', '/service/', '.ashx', '.asmx', 'handler', 'getdata', 'search', 'query']):
                entry["post_data"] = request.post_data
                api_calls.append(entry)
                print(f"[API] {request.method} {request.url[:100]}")

        page.on("request", log_request)

        print(f"\n=== Loading {BASE_URL}/?uid={MUNICIPALITY_UID} ===\n")

        # Load main page
        await page.goto(f"{BASE_URL}/?uid={MUNICIPALITY_UID}", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Screenshot
        await page.screenshot(path="screenshots/01_main.png", full_page=True)
        print("Screenshot: screenshots/01_main.png")

        # Get page title and content
        title = await page.title()
        print(f"Page title: {title}")

        # Find all navigation links
        print("\n=== Navigation Links ===")
        links = await page.query_selector_all("a")
        nav_links = []
        for link in links:
            try:
                href = await link.get_attribute("href") or ""
                text = (await link.inner_text()).strip()[:50]
                if href and text and not href.startswith("#") and not href.startswith("javascript"):
                    nav_links.append({"text": text, "href": href})
                    if any(x in text.lower() or x in href.lower() for x in ["water", "utility", "bill", "tax", "search", "account"]):
                        print(f"  * {text} -> {href}")
            except:
                pass

        # Find all forms
        print("\n=== Forms Found ===")
        forms = await page.query_selector_all("form")
        for i, form in enumerate(forms):
            action = await form.get_attribute("action") or "no action"
            method = await form.get_attribute("method") or "GET"
            print(f"  Form {i+1}: {method} -> {action}")

            # Get form inputs
            inputs = await form.query_selector_all("input, select")
            for inp in inputs:
                name = await inp.get_attribute("name") or await inp.get_attribute("id") or "unnamed"
                inp_type = await inp.get_attribute("type") or "text"
                placeholder = await inp.get_attribute("placeholder") or ""
                print(f"    - {name} ({inp_type}) {placeholder}")

        # Find search inputs
        print("\n=== Search Inputs ===")
        search_inputs = await page.query_selector_all('input[type="text"], input[type="search"], input[placeholder]')
        for inp in search_inputs:
            name = await inp.get_attribute("name") or await inp.get_attribute("id") or ""
            placeholder = await inp.get_attribute("placeholder") or ""
            if name or placeholder:
                print(f"  - {name}: {placeholder}")

        # Look for specific sections/modules
        print("\n=== Page Sections ===")
        sections = await page.query_selector_all("[class*='module'], [class*='section'], [class*='card'], [id*='module']")
        for sec in sections[:10]:
            class_name = await sec.get_attribute("class") or ""
            text = (await sec.inner_text())[:100].replace("\n", " ")
            print(f"  - {class_name[:40]}: {text[:60]}...")

        # Try clicking on common utility/search links
        print("\n=== Exploring Links ===")

        clickable_texts = ["Utility", "Water", "Bill", "Search", "Tax", "Account Lookup", "Pay Bill"]
        for text in clickable_texts:
            try:
                link = await page.query_selector(f'a:has-text("{text}")')
                if link:
                    href = await link.get_attribute("href")
                    print(f"  Found '{text}' link: {href}")

                    # Click and capture
                    await link.click()
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    await asyncio.sleep(1)

                    new_url = page.url
                    print(f"    Navigated to: {new_url}")
                    await page.screenshot(path=f"screenshots/page_{text.lower().replace(' ', '_')}.png", full_page=True)

                    # Check for new forms
                    new_forms = await page.query_selector_all("form")
                    if new_forms:
                        print(f"    Found {len(new_forms)} form(s) on this page")
                        for form in new_forms:
                            inputs = await form.query_selector_all("input[name], select[name]")
                            for inp in inputs:
                                name = await inp.get_attribute("name")
                                print(f"      Input: {name}")

                    # Go back
                    await page.go_back()
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"  Could not explore '{text}': {str(e)[:50]}")

        # Get full HTML for analysis
        html = await page.content()

        await browser.close()

    # Save results
    print("\n=== Saving Results ===")

    with open("discovery_results/all_requests.json", "w") as f:
        json.dump(requests_log, f, indent=2)
    print(f"Saved {len(requests_log)} requests to discovery_results/all_requests.json")

    with open("discovery_results/api_calls.json", "w") as f:
        json.dump(api_calls, f, indent=2)
    print(f"Saved {len(api_calls)} API calls to discovery_results/api_calls.json")

    with open("discovery_results/nav_links.json", "w") as f:
        json.dump(nav_links, f, indent=2)
    print(f"Saved {len(nav_links)} navigation links")

    with open("discovery_results/page.html", "w") as f:
        f.write(html)
    print("Saved page HTML")

    # Summary
    print("\n=== Summary ===")
    print(f"Total requests: {len(requests_log)}")
    print(f"API calls found: {len(api_calls)}")
    print(f"Screenshots saved to: screenshots/")

    return api_calls, nav_links

if __name__ == "__main__":
    asyncio.run(discover())
