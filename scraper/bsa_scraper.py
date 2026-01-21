"""
BSA Online Water Bill Scraper - City of Warren, MI

Uses Playwright to scrape water bill information from BSA Online portal.
Specifically configured for City of Warren Utility Billing.
"""

import asyncio
import logging
import re
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from dataclasses import dataclass

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from config import config

logger = logging.getLogger(__name__)


@dataclass
class BillData:
    """Parsed bill data from scraping"""
    account_number: str
    address: str
    amount_due: Decimal
    due_date: Optional[date]
    statement_date: Optional[date]
    previous_balance: Optional[Decimal] = None
    current_charges: Optional[Decimal] = None
    late_fees: Optional[Decimal] = None
    payments_received: Optional[Decimal] = None
    water_usage: Optional[int] = None
    owner_name: Optional[str] = None
    raw_data: Optional[str] = None


class BSAScraper:
    """
    Scraper for BSA Online water bill portal.
    Configured for City of Warren, Macomb County, MI (uid=305)
    """

    BASE_URL = "https://bsaonline.com"

    # City of Warren specific URLs
    UTILITY_SEARCH_URL = "/OnlinePayment/OnlinePaymentSearch?PaymentApplicationType=10"
    UTILITY_RESULTS_URL = "/OnlinePayment/OnlinePaymentSearchResults"

    def __init__(self, municipality_uid: str = None):
        self.municipality_uid = municipality_uid or config.bsa_municipality_uid
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._playwright = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """Start browser instance"""
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=config.headless_browser
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        self.page = await self.context.new_page()
        logger.info("Browser started")

    async def close(self):
        """Close browser instance"""
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed")

    def _build_url(self, path: str) -> str:
        """Build full URL with municipality UID"""
        separator = "&" if "?" in path else "?"
        return f"{self.BASE_URL}{path}{separator}uid={self.municipality_uid}"

    async def navigate_to_utility_search(self):
        """Navigate to the utility billing search page"""
        url = self._build_url(self.UTILITY_SEARCH_URL)
        await self.page.goto(url, wait_until="networkidle")
        await asyncio.sleep(1)
        logger.info(f"Navigated to utility billing search")

    async def search_by_account(self, account_number: str) -> Optional[BillData]:
        """
        Search for a property by account/reference number.
        Uses the Account Number search form on the utility billing page.
        """
        try:
            await self.navigate_to_utility_search()

            # Find the Account Number form
            # Form action: /OnlinePayment/OnlinePaymentSearch?PaymentSearchCategory=Account%20Number&PaymentApplicationType=UtilityBilling
            account_form = await self.page.query_selector('form[action*="Account"]')

            if not account_form:
                logger.error("Account Number form not found")
                return None

            # Fill account number
            account_input = await account_form.query_selector('input[name="AccountNumber"]')
            if not account_input:
                logger.error("AccountNumber input not found")
                return None

            await account_input.fill(account_number)

            # Submit form
            submit_btn = await account_form.query_selector('input[type="submit"]')
            if submit_btn:
                await submit_btn.click()
            else:
                await account_input.press("Enter")

            await self.page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)

            # Check if we got results
            return await self._parse_search_results(account_number)

        except Exception as e:
            logger.error(f"Account search failed for {account_number}: {e}")
            return None

    async def search_by_address(self, address: str) -> Optional[BillData]:
        """
        Search for a property by address.
        Uses the Address search form on the utility billing page.
        """
        try:
            await self.navigate_to_utility_search()

            # Find the Address form
            # Form action: /OnlinePayment/OnlinePaymentSearch?PaymentSearchCategory=Address&PaymentApplicationType=UtilityBilling
            address_form = await self.page.query_selector('form[action*="Address"]')

            if not address_form:
                logger.error("Address form not found")
                return None

            # Fill address
            address_input = await address_form.query_selector('input[name="Address"]')
            if not address_input:
                logger.error("Address input not found")
                return None

            await address_input.fill(address)

            # Submit form
            submit_btn = await address_form.query_selector('input[type="submit"]')
            if submit_btn:
                await submit_btn.click()
            else:
                await address_input.press("Enter")

            await self.page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)

            # Check if we got results
            return await self._parse_search_results(address)

        except Exception as e:
            logger.error(f"Address search failed for {address}: {e}")
            return None

    async def _parse_search_results(self, search_term: str) -> Optional[BillData]:
        """
        Parse the search results page or detail page.
        The site may go directly to detail page if only one result.
        """
        try:
            content = await self.page.content()
            current_url = self.page.url

            # Check for "No records to display"
            if "No records to display" in content:
                logger.info(f"No records found for: {search_term}")
                return None

            # Check if we're already on a detail/payment page (Step 3: Make Payment)
            if "Step 3: Make Payment" in content or "Account:" in content:
                logger.info("Already on detail page, parsing directly")
                return await self._parse_detail_page_direct()

            # Otherwise, look for results table and click first result
            # Table structure: Address | Reference # | Name | (action)
            rows = await self.page.query_selector_all("table tbody tr")

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 3:
                    address = await cells[0].inner_text()
                    reference_num = await cells[1].inner_text()

                    # Skip header-like rows
                    if "Address" in address and "Reference" in reference_num:
                        continue
                    if "Search:" in address or "By:" in reference_num:
                        continue

                    # Check for detail link
                    detail_link = await row.query_selector('a[href*="Detail"], a[href*="Payment"]')
                    if detail_link:
                        await detail_link.click()
                        await self.page.wait_for_load_state("networkidle")
                        await asyncio.sleep(1)
                        return await self._parse_detail_page_direct()

            return None

        except Exception as e:
            logger.error(f"Failed to parse search results: {e}")
            return None

    async def _parse_detail_page_direct(self) -> Optional[BillData]:
        """
        Parse the utility bill detail/payment page.
        This page shows account info and billing breakdown.

        Page structure (from inner_text):
        - Account: 302913026
        - 302913026 OCCUPANT
        - 3040 ALVINA
        - Warren, MI 48091-2498
        - Amount to Pay:
        - $116.97
        """
        try:
            # Get text content (easier to parse than HTML)
            body = await self.page.query_selector('body')
            text = await body.inner_text()
            lines = [l.strip() for l in text.split('\n') if l.strip()]

            # Extract account number
            account_number = ""
            for line in lines:
                if line.startswith("Account:"):
                    account_number = line.replace("Account:", "").strip()
                    break

            # Extract address - look for pattern: street address followed by "Warren, MI"
            address = ""
            owner_name = ""
            for i, line in enumerate(lines):
                # Owner/name line typically has "OCCUPANT" or is all caps before address
                if "OCCUPANT" in line.upper():
                    owner_name = line
                # Street address is typically a number followed by street name
                elif re.match(r'^\d+\s+[A-Z]', line.upper()) and "Warren" not in line:
                    street = line
                    # Next line should be city/state/zip
                    if i + 1 < len(lines) and "Warren" in lines[i + 1]:
                        city_state = lines[i + 1]
                        address = f"{street}, {city_state}"
                        break

            # Extract amount due - look for "Amount to Pay:" then get the next $ amount
            amount_due = Decimal("0")
            for i, line in enumerate(lines):
                if "Amount to Pay" in line:
                    # Check if amount is on same line
                    match = re.search(r'\$([\d,]+\.?\d*)', line)
                    if match:
                        amount_due = Decimal(match.group(1).replace(',', ''))
                    # Or check next line
                    elif i + 1 < len(lines):
                        next_line = lines[i + 1]
                        match = re.search(r'\$([\d,]+\.?\d*)', next_line)
                        if match:
                            amount_due = Decimal(match.group(1).replace(',', ''))
                    break

            # Extract individual charges
            charges = {}
            for line in lines:
                # Pattern: "CHARGE_NAME\t$XX.XX" or "CHARGE_NAME $XX.XX"
                if '\t' in line or '$' in line:
                    match = re.match(r'^([A-Z\s]+?)\s*\$?([\d,]+\.\d{2})$', line)
                    if match:
                        name = match.group(1).strip()
                        try:
                            amount = Decimal(match.group(2).replace(',', ''))
                            charges[name] = amount
                        except:
                            pass

            current_charges = sum(charges.values()) if charges else None

            logger.info(f"Parsed: Account={account_number}, Address={address}, Amount=${amount_due}")

            return BillData(
                account_number=account_number,
                address=address,
                amount_due=amount_due,
                due_date=None,
                statement_date=None,
                previous_balance=None,
                current_charges=current_charges,
                late_fees=None,
                water_usage=None,
                owner_name=owner_name if owner_name else None,
                raw_data=text[:5000]
            )

        except Exception as e:
            logger.error(f"Failed to parse detail page: {e}")
            return None

    async def _parse_detail_page(self, account_number: str, address: str, owner_name: str) -> Optional[BillData]:
        """
        Parse the bill detail page to get amount due, dates, etc.
        """
        try:
            content = await self.page.content()

            # Initialize data
            amount_due = Decimal("0")
            due_date = None
            statement_date = None
            previous_balance = None
            current_charges = None
            late_fees = None
            water_usage = None

            # Look for amount due
            # Common patterns: "Amount Due", "Balance", "Total Due"
            amount_patterns = [
                r'(?:Amount\s*Due|Balance|Total\s*Due)[:\s]*\$?([\d,]+\.?\d*)',
                r'\$\s*([\d,]+\.\d{2})',
            ]
            for pattern in amount_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    try:
                        amount_due = Decimal(match.group(1).replace(',', ''))
                        break
                    except:
                        pass

            # Look for due date
            date_patterns = [
                r'(?:Due\s*Date|Payment\s*Due)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                r'Due[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            ]
            for pattern in date_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    due_date = self._parse_date(match.group(1))
                    if due_date:
                        break

            # Look for previous balance
            prev_match = re.search(r'(?:Previous\s*Balance)[:\s]*\$?([\d,]+\.?\d*)', content, re.IGNORECASE)
            if prev_match:
                try:
                    previous_balance = Decimal(prev_match.group(1).replace(',', ''))
                except:
                    pass

            # Look for current charges
            curr_match = re.search(r'(?:Current\s*Charges?)[:\s]*\$?([\d,]+\.?\d*)', content, re.IGNORECASE)
            if curr_match:
                try:
                    current_charges = Decimal(curr_match.group(1).replace(',', ''))
                except:
                    pass

            # Look for late fees
            late_match = re.search(r'(?:Late\s*Fee|Penalty)[:\s]*\$?([\d,]+\.?\d*)', content, re.IGNORECASE)
            if late_match:
                try:
                    late_fees = Decimal(late_match.group(1).replace(',', ''))
                except:
                    pass

            # Look for water usage
            usage_match = re.search(r'(?:Usage|Consumption)[:\s]*([\d,]+)\s*(?:gal|gallons)?', content, re.IGNORECASE)
            if usage_match:
                try:
                    water_usage = int(usage_match.group(1).replace(',', ''))
                except:
                    pass

            return BillData(
                account_number=account_number,
                address=address,
                amount_due=amount_due,
                due_date=due_date,
                statement_date=statement_date,
                previous_balance=previous_balance,
                current_charges=current_charges,
                late_fees=late_fees,
                water_usage=water_usage,
                owner_name=owner_name,
                raw_data=content[:5000]
            )

        except Exception as e:
            logger.error(f"Failed to parse detail page: {e}")
            return BillData(
                account_number=account_number,
                address=address,
                amount_due=Decimal("0"),
                due_date=None,
                statement_date=None,
                owner_name=owner_name
            )

    def _parse_date(self, date_str: str) -> Optional[date]:
        """Parse date string to date object"""
        formats = [
            '%m/%d/%Y', '%m-%d-%Y',
            '%m/%d/%y', '%m-%d-%y',
            '%Y-%m-%d',
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        return None

    async def scrape_all_properties(self, identifiers: List[str], search_type: str = "account") -> List[BillData]:
        """
        Scrape bill data for multiple properties.

        Args:
            identifiers: List of account numbers or addresses
            search_type: "account" or "address"
        """
        results = []

        for identifier in identifiers:
            logger.info(f"Scraping {search_type}: {identifier}")

            if search_type == "account":
                bill_data = await self.search_by_account(identifier)
            else:
                bill_data = await self.search_by_address(identifier)

            if bill_data:
                results.append(bill_data)
                logger.info(f"Found: {bill_data.address} - ${bill_data.amount_due}")
            else:
                logger.warning(f"No data found for: {identifier}")

            # Rate limiting - be nice to the server
            await asyncio.sleep(2)

        return results

    async def screenshot(self, filename: str):
        """Take a screenshot for debugging"""
        await self.page.screenshot(path=filename, full_page=True)
        logger.info(f"Screenshot saved: {filename}")


# Quick test function
async def test_scraper():
    """Test the scraper with a sample search"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python bsa_scraper.py <address_or_account>")
        print("Example: python bsa_scraper.py '12345 Main St'")
        return

    search_term = sys.argv[1]

    async with BSAScraper() as scraper:
        print(f"\nSearching for: {search_term}")

        # Try address search first
        result = await scraper.search_by_address(search_term)

        if not result:
            # Try account search
            result = await scraper.search_by_account(search_term)

        if result:
            print(f"\n=== Result ===")
            print(f"Address: {result.address}")
            print(f"Account: {result.account_number}")
            print(f"Amount Due: ${result.amount_due}")
            print(f"Due Date: {result.due_date}")
            print(f"Owner: {result.owner_name}")
        else:
            print("No results found")

        await scraper.screenshot("screenshots/test_result.png")


if __name__ == "__main__":
    asyncio.run(test_scraper())
