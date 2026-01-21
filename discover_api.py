#!/usr/bin/env python3
"""
BSA Online API Discovery Script

This script uses Playwright to:
1. Load the BSA Online portal
2. Intercept all network requests to find API endpoints
3. Analyze request/response patterns
4. Output discovered endpoints for use in the scraper
"""

import asyncio
import json
from datetime import datetime
from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table

console = Console()

# Configuration
BASE_URL = "https://bsaonline.com"
MUNICIPALITY_UID = "305"  # Your specific municipality

class APIDiscovery:
    def __init__(self):
        self.requests = []
        self.api_endpoints = []

    async def capture_request(self, request):
        """Capture all network requests"""
        entry = {
            "url": request.url,
            "method": request.method,
            "resource_type": request.resource_type,
            "headers": dict(request.headers),
            "post_data": request.post_data if request.method == "POST" else None,
            "timestamp": datetime.now().isoformat()
        }
        self.requests.append(entry)

        # Identify potential API calls
        if any(pattern in request.url.lower() for pattern in [
            '/api/', '/service/', '/data/', '/search/', '/query/',
            '.ashx', '.asmx', '/handler/', 'getdata', 'fetch',
            'account', 'bill', 'water', 'utility', 'balance'
        ]):
            self.api_endpoints.append(entry)
            console.print(f"[green]API Found:[/green] {request.method} {request.url}")

    async def capture_response(self, response):
        """Capture responses for API calls"""
        if response.url in [r["url"] for r in self.api_endpoints]:
            try:
                body = await response.text()
                # Try to parse as JSON
                try:
                    json_body = json.loads(body)
                    console.print(f"[cyan]JSON Response from {response.url}:[/cyan]")
                    console.print_json(data=json_body)
                except json.JSONDecodeError:
                    if len(body) < 500:
                        console.print(f"[yellow]Response from {response.url}:[/yellow] {body[:200]}")
            except Exception as e:
                console.print(f"[red]Error reading response: {e}[/red]")

    async def discover(self):
        """Main discovery routine"""
        console.print("[bold blue]Starting BSA Online API Discovery[/bold blue]")
        console.print(f"Target: {BASE_URL}/?uid={MUNICIPALITY_UID}\n")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)  # Set to True for headless
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            # Set up request/response interception
            page.on("request", self.capture_request)
            page.on("response", self.capture_response)

            try:
                # Step 1: Load main page
                console.print("[bold]Step 1: Loading main page...[/bold]")
                await page.goto(f"{BASE_URL}/?uid={MUNICIPALITY_UID}", wait_until="networkidle")
                await asyncio.sleep(2)

                # Take screenshot for reference
                await page.screenshot(path="screenshots/01_main_page.png", full_page=True)
                console.print("[green]Screenshot saved: screenshots/01_main_page.png[/green]")

                # Step 2: Look for search/lookup options
                console.print("\n[bold]Step 2: Analyzing page structure...[/bold]")

                # Get page content for analysis
                content = await page.content()

                # Look for common elements
                search_forms = await page.query_selector_all('form, input[type="search"], input[type="text"]')
                console.print(f"Found {len(search_forms)} form/input elements")

                # Look for navigation links
                nav_links = await page.query_selector_all('a[href*="Search"], a[href*="Bill"], a[href*="Water"], a[href*="Utility"], a[href*="Account"]')
                for link in nav_links:
                    href = await link.get_attribute("href")
                    text = await link.inner_text()
                    console.print(f"[cyan]Navigation link:[/cyan] {text} -> {href}")

                # Step 3: Try to find and click on Water/Utility section
                console.print("\n[bold]Step 3: Looking for utility/water bill sections...[/bold]")

                # Common selectors for utility sections
                selectors_to_try = [
                    'text=Water',
                    'text=Utility',
                    'text=Bill',
                    'text=Account',
                    'a:has-text("Search")',
                    'button:has-text("Search")',
                    '[class*="water"]',
                    '[class*="utility"]',
                    '[class*="bill"]',
                ]

                for selector in selectors_to_try:
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            text = await element.inner_text()
                            console.print(f"[green]Found element:[/green] '{selector}' -> '{text[:50]}'")
                    except Exception:
                        pass

                # Step 4: Interactive exploration
                console.print("\n[bold]Step 4: Manual exploration mode[/bold]")
                console.print("Browser is open. Navigate to the water bill section manually.")
                console.print("All network requests are being captured.")
                console.print("Press Enter in the terminal when done exploring...")

                # Wait for user to explore
                await asyncio.get_event_loop().run_in_executor(None, input)

                # Take final screenshot
                await page.screenshot(path="screenshots/02_final_state.png", full_page=True)

            except Exception as e:
                console.print(f"[red]Error during discovery: {e}[/red]")

            finally:
                await browser.close()

        # Output results
        self.print_results()
        self.save_results()

    def print_results(self):
        """Print discovered API endpoints"""
        console.print("\n[bold blue]═══ Discovery Results ═══[/bold blue]\n")

        if self.api_endpoints:
            table = Table(title="Discovered API Endpoints")
            table.add_column("Method", style="cyan")
            table.add_column("URL", style="green")
            table.add_column("Type", style="yellow")

            for endpoint in self.api_endpoints:
                table.add_row(
                    endpoint["method"],
                    endpoint["url"][:80] + "..." if len(endpoint["url"]) > 80 else endpoint["url"],
                    endpoint["resource_type"]
                )

            console.print(table)
        else:
            console.print("[yellow]No obvious API endpoints found. Check all_requests.json for full list.[/yellow]")

        console.print(f"\n[bold]Total requests captured: {len(self.requests)}[/bold]")

    def save_results(self):
        """Save results to files for analysis"""
        # Save all requests
        with open("discovery_results/all_requests.json", "w") as f:
            json.dump(self.requests, f, indent=2)

        # Save API endpoints
        with open("discovery_results/api_endpoints.json", "w") as f:
            json.dump(self.api_endpoints, f, indent=2)

        # Save unique domains/paths
        paths = set()
        for req in self.requests:
            from urllib.parse import urlparse
            parsed = urlparse(req["url"])
            paths.add(f"{parsed.netloc}{parsed.path}")

        with open("discovery_results/unique_paths.txt", "w") as f:
            for path in sorted(paths):
                f.write(path + "\n")

        console.print("\n[green]Results saved to discovery_results/[/green]")


async def main():
    import os
    os.makedirs("screenshots", exist_ok=True)
    os.makedirs("discovery_results", exist_ok=True)

    discovery = APIDiscovery()
    await discovery.discover()


if __name__ == "__main__":
    asyncio.run(main())
