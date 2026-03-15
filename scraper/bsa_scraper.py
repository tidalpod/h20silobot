"""
BSA Online Water Bill Scraper - City of Warren, MI

Uses HTTP requests (aiohttp) to scrape water bill information from BSA Online portal.
Falls back to Playwright browser if needed.
Specifically configured for City of Warren Utility Billing.
"""

import asyncio
import logging
import re
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from dataclasses import dataclass

import aiohttp
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

try:
    from playwright_stealth import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

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
    parcel_number: Optional[str] = None
    raw_data: Optional[str] = None


@dataclass
class TaxData:
    """Parsed property tax data from scraping"""
    parcel_number: str
    address: str
    tax_year: int
    amount_due: Decimal
    due_date: Optional[date] = None
    status: Optional[str] = None  # paid, due, delinquent
    owner_name: Optional[str] = None
    taxable_value: Optional[Decimal] = None
    raw_data: Optional[str] = None


class BSAScraper:
    """
    Scraper for BSA Online water bill portal.
    Supports multiple Macomb County municipalities.
    """

    BASE_URL = "https://bsaonline.com"

    # BSA Online municipality UIDs for Macomb County cities
    MUNICIPALITY_UIDS = {
        "warren": "305",
        "roseville": "327",
        "eastpointe": "255",
    }

    # URL paths (same across municipalities)
    UTILITY_SEARCH_URL = "/OnlinePayment/OnlinePaymentSearch?PaymentApplicationType=10"
    UTILITY_RESULTS_URL = "/OnlinePayment/OnlinePaymentSearchResults"

    # Property Tax URLs (PaymentApplicationType=2 is typically property tax)
    TAX_SEARCH_URL = "/OnlinePayment/OnlinePaymentSearch?PaymentApplicationType=2"

    @classmethod
    def get_uid_for_city(cls, city: str) -> str:
        """Get BSA Online UID for a city name. Returns Warren UID as default."""
        if not city:
            return cls.MUNICIPALITY_UIDS["warren"]
        city_lower = city.lower().strip()
        return cls.MUNICIPALITY_UIDS.get(city_lower, cls.MUNICIPALITY_UIDS["warren"])

    @classmethod
    async def http_search_by_account(cls, account_number: str, municipality_uid: str = "305") -> Optional['BillData']:
        """
        Search by account number using direct HTTP requests (no browser needed).
        Bypasses reCAPTCHA since it's a client-side JavaScript check.
        """
        return await cls._http_search(
            search_category="Account Number",
            search_text=account_number,
            municipality_uid=municipality_uid,
        )

    @classmethod
    async def http_search_by_address(cls, address: str, municipality_uid: str = "305") -> Optional['BillData']:
        """
        Search by address using direct HTTP requests (no browser needed).
        """
        return await cls._http_search(
            search_category="Address",
            search_text=address,
            municipality_uid=municipality_uid,
        )

    @classmethod
    async def _http_search(cls, search_category: str, search_text: str, municipality_uid: str) -> Optional['BillData']:
        """Perform a search via HTTP POST and parse the HTML response."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"https://bsaonline.com/OnlinePayment/OnlinePaymentSearch?PaymentApplicationType=10&uid={municipality_uid}",
        }

        search_url = f"{cls.BASE_URL}/OnlinePayment/OnlinePaymentSearchResults"
        params = {
            "PaymentSearchCategory": search_category,
            "PaymentApplicationType": "UtilityBilling",
            "PaymentSearchText": search_text,
            "uid": municipality_uid,
        }

        try:
            async with aiohttp.ClientSession() as session:
                # First hit the search page to get cookies/session
                search_page_url = f"{cls.BASE_URL}/OnlinePayment/OnlinePaymentSearch?PaymentApplicationType=10&uid={municipality_uid}"
                async with session.get(search_page_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    logger.info(f"HTTP search page: status={resp.status}, url={resp.url}")

                # Now submit the search
                async with session.get(search_url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True) as resp:
                    final_url = str(resp.url)
                    logger.info(f"HTTP search results: status={resp.status}, url={final_url}")

                    # Check if we got redirected to validation
                    if "ValidateUser" in final_url or "pendingCaptcha" in final_url:
                        logger.warning("HTTP search redirected to validation page — trying POST form submission")
                        # Try submitting via POST instead
                        form_action = f"{cls.BASE_URL}/OnlinePayment/OnlinePaymentSearch"
                        form_params = {
                            "PaymentSearchCategory": search_category,
                            "PaymentApplicationType": "UtilityBilling",
                        }
                        form_data = {}
                        if search_category == "Account Number":
                            form_data["AccountNumber"] = search_text
                            form_params["PaymentSearchCategory"] = "Account Number"
                        else:
                            form_data["Address"] = search_text
                            form_params["PaymentSearchCategory"] = "Address"

                        async with session.post(
                            form_action,
                            params=form_params,
                            data=form_data,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=15),
                            allow_redirects=True,
                        ) as post_resp:
                            final_url = str(post_resp.url)
                            logger.info(f"HTTP POST result: status={post_resp.status}, url={final_url}")

                            if "ValidateUser" in final_url or "pendingCaptcha" in final_url:
                                logger.warning("HTTP POST also redirected to validation — CAPTCHA required")
                                return None

                            html = await post_resp.text()
                            return cls._parse_html_results(html, search_text)

                    html = await resp.text()
                    return cls._parse_html_results(html, search_text)

        except Exception as e:
            logger.error(f"HTTP search failed for {search_text}: {e}")
            return None

    @classmethod
    def _parse_html_results(cls, html: str, search_term: str) -> Optional['BillData']:
        """Parse bill data from HTML response (search results or detail page)."""
        if not html:
            return None

        # Check for no records
        if "No records to display" in html:
            logger.info(f"No records found for: {search_term}")
            return None

        # Strip HTML tags to get text content
        text = re.sub(r'<[^>]+>', '\n', html)
        text = re.sub(r'\n\s*\n', '\n', text)
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        # Check if this is a detail/payment page
        is_detail = "Amount to Pay" in text or "Step 3: Make Payment" in text

        if not is_detail:
            # This might be a results list — try to find a detail link URL
            detail_match = re.search(r'href="(/OnlinePayment/OnlinePaymentDetail[^"]*)"', html)
            if not detail_match:
                detail_match = re.search(r'href="(/OnlinePayment/[^"]*Detail[^"]*)"', html)
            if detail_match:
                logger.info(f"Found detail link in results: {detail_match.group(1)}")
                # We'd need to follow this link — return None for now and let caller retry
                # Store the detail URL for the caller
                return None

            logger.warning(f"Not a detail page and no detail links found for: {search_term}")
            logger.warning(f"HTML preview: {text[:500]}")
            return None

        # Parse the detail page
        account_number = ""
        for line in lines:
            if line.startswith("Account:"):
                account_number = line.replace("Account:", "").strip()
                break
            # Also try "Account" followed by a number
            m = re.match(r'^Account\s*#?\s*:?\s*(\d+)', line)
            if m:
                account_number = m.group(1)
                break

        # Extract address
        address = ""
        owner_name = ""
        mi_cities = ["Warren", "Roseville", "Eastpointe"]
        for i, line in enumerate(lines):
            if "OCCUPANT" in line.upper():
                owner_name = line
            elif re.match(r'^\d+\s+[A-Z]', line.upper()) and not any(c in line for c in mi_cities):
                street = line
                if i + 1 < len(lines) and ("MI" in lines[i + 1] or any(c in lines[i + 1] for c in mi_cities)):
                    address = f"{street}, {lines[i + 1]}"
                    break

        # Extract amount due
        amount_due = Decimal("0")
        for i, line in enumerate(lines):
            if "Amount to Pay" in line:
                match = re.search(r'\$([\d,]+\.?\d*)', line)
                if match:
                    amount_due = Decimal(match.group(1).replace(',', ''))
                elif i + 1 < len(lines):
                    match = re.search(r'\$([\d,]+\.?\d*)', lines[i + 1])
                    if match:
                        amount_due = Decimal(match.group(1).replace(',', ''))
                break

        logger.info(f"HTTP parsed: Account={account_number}, Address={address}, Amount=${amount_due}")

        return BillData(
            account_number=account_number,
            address=address,
            amount_due=amount_due,
            due_date=None,
            statement_date=None,
            previous_balance=None,
            current_charges=None,
            late_fees=None,
            water_usage=None,
            owner_name=owner_name if owner_name else None,
            raw_data=text[:5000],
        )

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
        """Start browser instance with stealth to bypass bot detection"""
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=config.headless_browser,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        self.page = await self.context.new_page()
        if HAS_STEALTH:
            await stealth_async(self.page)
            logger.info("Browser started (stealth mode)")
        else:
            logger.warning("Browser started (playwright-stealth not installed, running without stealth)")

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
        """Navigate to the utility billing search page, handling security verification"""
        url = self._build_url(self.UTILITY_SEARCH_URL)
        await self.page.goto(url, wait_until="networkidle")
        await asyncio.sleep(1)

        title = await self.page.title()
        logger.info(f"Navigated to utility billing search (title: {title}, url: {self.page.url})")

    async def search_by_account(self, account_number: str) -> Optional[BillData]:
        """
        Search for a property by account/reference number.
        Uses the Account Number search form on the utility billing page.
        """
        try:
            await self.navigate_to_utility_search()

            # Find the Account Number form
            # Form action: /OnlinePayment/OnlinePaymentSearch?PaymentSearchCategory=Account%20Number&PaymentApplicationType=UtilityBilling
            # Debug: list all forms on page
            all_forms = await self.page.query_selector_all('form')
            form_actions = []
            for f in all_forms:
                action = await f.get_attribute('action') or 'no-action'
                form_actions.append(action)
            logger.info(f"Forms on page: {form_actions}")

            account_form = await self.page.query_selector('form[action*="Account"]')

            if not account_form:
                # Try alternate selectors
                account_form = await self.page.query_selector('form[action*="account"]')
            if not account_form:
                logger.error(f"Account Number form not found. Page URL: {self.page.url}")
                # Log first 500 chars of page text for debugging
                body = await self.page.query_selector('body')
                if body:
                    text = await body.inner_text()
                    logger.error(f"Page text preview: {text[:500]}")
                return None

            # Fill account number
            account_input = await account_form.query_selector('input[name="AccountNumber"]')
            if not account_input:
                # Try alternate input names
                account_input = await account_form.query_selector('input[type="text"]')
            if not account_input:
                logger.error("AccountNumber input not found in form")
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
                address_form = await self.page.query_selector('form[action*="address"]')
            if not address_form:
                logger.error(f"Address form not found. Page URL: {self.page.url}")
                body = await self.page.query_selector('body')
                if body:
                    text = await body.inner_text()
                    logger.error(f"Page text preview: {text[:500]}")
                return None

            # Fill address
            address_input = await address_form.query_selector('input[name="Address"]')
            if not address_input:
                address_input = await address_form.query_selector('input[type="text"]')
            if not address_input:
                logger.error("Address input not found in form")
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

    async def _handle_post_submit_verification(self) -> bool:
        """
        Handle security verification that appears AFTER submitting a search form.
        BSA Online redirects to /Account/ValidateUser with a returnUrl.
        Returns True if verification was handled and we should re-check the page.
        """
        current_url = self.page.url
        if "ValidateUser" not in current_url and "pendingCaptcha" not in current_url:
            return False

        logger.info(f"Security verification after form submit (URL: {current_url})")

        # Complete the verification
        await self._handle_security_verification()

        # After verification, check if we got redirected to results
        await asyncio.sleep(2)
        new_url = self.page.url

        if "ValidateUser" in new_url or "pendingCaptcha" in new_url:
            # Verification might not have redirected — extract returnUrl and navigate directly
            import urllib.parse
            parsed = urllib.parse.urlparse(current_url)
            params = urllib.parse.parse_qs(parsed.query)
            return_url = params.get("returnUrl", [None])[0]

            if return_url:
                # returnUrl is URL-encoded, decode it
                full_url = f"{self.BASE_URL}{return_url}"
                logger.info(f"Navigating directly to return URL: {full_url}")
                await self.page.goto(full_url, wait_until="networkidle")
                await asyncio.sleep(1)

                # Check if we hit verification AGAIN
                if "ValidateUser" in self.page.url:
                    logger.warning("Still on verification page after direct navigation")
                    return False

                return True
            return False

        logger.info(f"Verification redirected to: {new_url}")
        return True

    async def _parse_search_results(self, search_term: str) -> Optional[BillData]:
        """
        Parse the search results page or detail page.
        The site may go directly to detail page if only one result.
        """
        try:
            # Check if we landed on security verification page after form submit
            if await self._handle_post_submit_verification():
                logger.info("Verification completed, parsing results")

            content = await self.page.content()
            current_url = self.page.url
            logger.info(f"Search results URL: {current_url}")

            # Get page text for debugging
            body = await self.page.query_selector('body')
            page_text = await body.inner_text() if body else ""

            # If still on verification page, we can't proceed
            if "ValidateUser" in current_url or "Security Verification" in page_text:
                logger.warning(f"Stuck on security verification for: {search_term}")
                return None

            # Check for "No records to display"
            if "No records to display" in content or "No records to display" in page_text:
                logger.info(f"No records found for: {search_term}")
                return None

            # Check if we're already on a detail/payment page (Step 3: Make Payment)
            if "Step 3: Make Payment" in content or "Step 3: Make Payment" in page_text:
                logger.info("On detail page (Step 3), parsing directly")
                return await self._parse_detail_page_direct()

            if "Account:" in page_text and "Amount to Pay" in page_text:
                logger.info("On detail page (Account + Amount to Pay), parsing directly")
                return await self._parse_detail_page_direct()

            # Otherwise, look for results table and click first result
            rows = await self.page.query_selector_all("table tbody tr")
            logger.info(f"Found {len(rows)} table rows on results page")

            if len(rows) == 0:
                rows = await self.page.query_selector_all("table tr")
                logger.info(f"Alternate selector found {len(rows)} rows")

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 3:
                    address = await cells[0].inner_text()
                    reference_num = await cells[1].inner_text()

                    if "Address" in address and "Reference" in reference_num:
                        continue
                    if "Search:" in address or "By:" in reference_num:
                        continue

                    logger.info(f"Result row: {address.strip()} | {reference_num.strip()}")

                    detail_link = await row.query_selector('a[href*="Detail"], a[href*="Payment"]')
                    if detail_link:
                        await detail_link.click()
                        await self.page.wait_for_load_state("networkidle")
                        await asyncio.sleep(1)

                        # Check for verification again after clicking detail link
                        if await self._handle_post_submit_verification():
                            logger.info("Verification after detail click, parsing")

                        return await self._parse_detail_page_direct()

            # Nothing matched
            logger.warning(f"Could not parse results for: {search_term}")
            logger.warning(f"Page text (first 800 chars): {page_text[:800]}")
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

            # Extract address - look for pattern: street address followed by city, MI
            address = ""
            owner_name = ""
            mi_cities = ["Warren", "Roseville", "Eastpointe"]
            for i, line in enumerate(lines):
                # Owner/name line typically has "OCCUPANT" or is all caps before address
                if "OCCUPANT" in line.upper():
                    owner_name = line
                # Street address is typically a number followed by street name
                elif re.match(r'^\d+\s+[A-Z]', line.upper()) and not any(c in line for c in mi_cities):
                    street = line
                    # Next line should be city/state/zip (any supported MI city)
                    if i + 1 < len(lines) and ("MI" in lines[i + 1] or any(c in lines[i + 1] for c in mi_cities)):
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

            # Try to get parcel number from "View Additional Account Information" link
            parcel_number = None
            try:
                additional_info_link = await self.page.query_selector('a:has-text("Additional Account Information"), a:has-text("Additional Information")')
                if additional_info_link:
                    # Open in new tab or click
                    await additional_info_link.click()
                    await self.page.wait_for_load_state("networkidle")
                    await asyncio.sleep(1)

                    # Get the additional info page content
                    additional_body = await self.page.query_selector('body')
                    additional_text = await additional_body.inner_text()

                    # Look for parcel number patterns
                    parcel_patterns = [
                        r'Parcel[:\s#]*([0-9-]+)',
                        r'Parcel Number[:\s]*([0-9-]+)',
                        r'Property ID[:\s]*([0-9-]+)',
                        r'PIN[:\s]*([0-9-]+)',
                    ]
                    for pattern in parcel_patterns:
                        match = re.search(pattern, additional_text, re.IGNORECASE)
                        if match:
                            parcel_number = match.group(1).strip()
                            logger.info(f"Found parcel number: {parcel_number}")
                            break

                    # Go back to the payment page
                    await self.page.go_back()
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Could not extract parcel number: {e}")

            logger.info(f"Parsed: Account={account_number}, Address={address}, Amount=${amount_due}, Parcel={parcel_number}")

            return BillData(
                account_number=account_number,
                address=address,
                amount_due=amount_due,
                due_date=None,
                statement_date=None,
                previous_balance=None,
                parcel_number=parcel_number,
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

    # =========================================================================
    # Property Tax Scraping Methods
    # =========================================================================

    async def navigate_to_tax_search(self):
        """Navigate to the property tax search page"""
        url = self._build_url(self.TAX_SEARCH_URL)
        await self.page.goto(url, wait_until="networkidle")
        await asyncio.sleep(1)

        # Handle security verification checkbox if present
        await self._handle_security_verification()

        logger.info(f"Navigated to property tax search")

    async def _handle_security_verification(self):
        """Handle BSA Online's reCAPTCHA v3 security verification"""
        try:
            # Check if page has security verification content
            body = await self.page.query_selector('body')
            page_text = await body.inner_text() if body else ""

            if "verify you are a human" not in page_text.lower() and "security" not in page_text.lower():
                return  # No verification needed

            logger.info("Security verification page detected")

            # Look for the verification checkbox
            selectors = [
                'input[type="checkbox"]',
                '.verification-checkbox',
                '#verifyCheckbox',
                'input[name*="verify"]',
                'input[name*="Verify"]',
                'input[id*="verify"]',
                'input[id*="Verify"]',
            ]

            for selector in selectors:
                checkbox = await self.page.query_selector(selector)
                if checkbox:
                    is_visible = await checkbox.is_visible()
                    is_checked = await checkbox.is_checked()

                    if is_visible and not is_checked:
                        logger.info("Clicking security checkbox...")
                        await checkbox.click()
                        # Wait for reCAPTCHA v3 to process (needs more time)
                        await asyncio.sleep(3)

                        # Look for verify/submit button
                        verify_btns = [
                            'button:has-text("Verify")',
                            'a:has-text("Verify")',
                            'input[type="submit"][value*="Verify"]',
                            'button:has-text("Continue")',
                            'input[type="submit"]',
                        ]
                        for btn_selector in verify_btns:
                            btn = await self.page.query_selector(btn_selector)
                            if btn and await btn.is_visible():
                                logger.info(f"Clicking verify button: {btn_selector}")
                                await btn.click()
                                await self.page.wait_for_load_state("networkidle")
                                await asyncio.sleep(2)
                                break

                        # Check if verification succeeded
                        new_url = self.page.url
                        if "pendingCaptcha" in new_url or "ValidateUser" in new_url:
                            logger.warning(f"Verification may have failed (URL: {new_url})")
                        else:
                            logger.info("Security verification completed successfully")
                        return

            # Try reCAPTCHA iframe
            frames = self.page.frames
            for frame in frames:
                if 'recaptcha' in frame.url.lower():
                    checkbox = await frame.query_selector('.recaptcha-checkbox')
                    if checkbox:
                        await checkbox.click()
                        await asyncio.sleep(3)
                        logger.info("Clicked reCAPTCHA checkbox in iframe")
                        return

        except Exception as e:
            logger.warning(f"Security verification handling failed: {e}")

    async def search_tax_by_parcel(self, parcel_number: str) -> Optional[TaxData]:
        """
        Search for property tax by parcel number.
        """
        try:
            await self.navigate_to_tax_search()

            # Find the Parcel Number form
            parcel_form = await self.page.query_selector('form[action*="Parcel"]')

            if not parcel_form:
                # Try generic form with parcel input
                parcel_input = await self.page.query_selector('input[name="ParcelNumber"], input[name="Parcel"]')
                if parcel_input:
                    await parcel_input.fill(parcel_number)
                    await parcel_input.press("Enter")
                else:
                    logger.error("Parcel Number form/input not found")
                    return None
            else:
                # Fill parcel number in form
                parcel_input = await parcel_form.query_selector('input[name="ParcelNumber"], input[name="Parcel"]')
                if not parcel_input:
                    logger.error("ParcelNumber input not found in form")
                    return None

                await parcel_input.fill(parcel_number)

                # Submit form
                submit_btn = await parcel_form.query_selector('input[type="submit"]')
                if submit_btn:
                    await submit_btn.click()
                else:
                    await parcel_input.press("Enter")

            await self.page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)

            return await self._parse_tax_results(parcel_number)

        except Exception as e:
            logger.error(f"Tax parcel search failed for {parcel_number}: {e}")
            return None

    async def search_tax_by_address(self, address: str) -> Optional[TaxData]:
        """
        Search for property tax by address.
        """
        try:
            await self.navigate_to_tax_search()

            # Find the Address form
            address_form = await self.page.query_selector('form[action*="Address"]')

            if not address_form:
                # Try generic form with address input
                address_input = await self.page.query_selector('input[name="Address"]')
                if address_input:
                    await address_input.fill(address)
                    await address_input.press("Enter")
                else:
                    logger.error("Address form/input not found")
                    return None
            else:
                address_input = await address_form.query_selector('input[name="Address"]')
                if not address_input:
                    logger.error("Address input not found in form")
                    return None

                await address_input.fill(address)

                submit_btn = await address_form.query_selector('input[type="submit"]')
                if submit_btn:
                    await submit_btn.click()
                else:
                    await address_input.press("Enter")

            await self.page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)

            return await self._parse_tax_results(address)

        except Exception as e:
            logger.error(f"Tax address search failed for {address}: {e}")
            return None

    async def _parse_tax_results(self, search_term: str) -> Optional[TaxData]:
        """
        Parse property tax search results.
        """
        try:
            content = await self.page.content()

            # Check for "No records to display"
            if "No records to display" in content or "no results" in content.lower():
                logger.info(f"No tax records found for: {search_term}")
                return None

            # Get text content for parsing
            body = await self.page.query_selector('body')
            text = await body.inner_text()
            lines = [l.strip() for l in text.split('\n') if l.strip()]

            # Try to click on first result if we're on a results list
            rows = await self.page.query_selector_all("table tbody tr")
            for row in rows:
                detail_link = await row.query_selector('a[href*="Detail"], a[href*="Payment"]')
                if detail_link:
                    await detail_link.click()
                    await self.page.wait_for_load_state("networkidle")
                    await asyncio.sleep(1)
                    body = await self.page.query_selector('body')
                    text = await body.inner_text()
                    lines = [l.strip() for l in text.split('\n') if l.strip()]
                    break

            # Extract parcel number
            parcel_number = ""
            for line in lines:
                if "Parcel" in line and "#" in line:
                    match = re.search(r'[\d-]+', line)
                    if match:
                        parcel_number = match.group()
                        break
                elif line.startswith("Parcel:"):
                    parcel_number = line.replace("Parcel:", "").strip()
                    break

            # Extract address
            address = ""
            for i, line in enumerate(lines):
                if re.match(r'^\d+\s+[A-Z]', line.upper()) and "Warren" not in line:
                    address = line
                    if i + 1 < len(lines) and ("Warren" in lines[i + 1] or "MI" in lines[i + 1]):
                        address = f"{line}, {lines[i + 1]}"
                    break

            # Extract amount due
            amount_due = Decimal("0")
            for i, line in enumerate(lines):
                if any(term in line.lower() for term in ["amount due", "total due", "balance", "amount to pay"]):
                    match = re.search(r'\$([\d,]+\.?\d*)', line)
                    if match:
                        amount_due = Decimal(match.group(1).replace(',', ''))
                    elif i + 1 < len(lines):
                        match = re.search(r'\$([\d,]+\.?\d*)', lines[i + 1])
                        if match:
                            amount_due = Decimal(match.group(1).replace(',', ''))
                    break

            # Extract tax year
            tax_year = datetime.now().year
            for line in lines:
                match = re.search(r'(?:Tax\s*Year|Year)[:\s]*(\d{4})', line, re.IGNORECASE)
                if match:
                    tax_year = int(match.group(1))
                    break

            # Extract owner name
            owner_name = ""
            for line in lines:
                if "owner" in line.lower():
                    owner_name = re.sub(r'^owner[:\s]*', '', line, flags=re.IGNORECASE).strip()
                    break

            # Determine status
            status = "due"
            text_lower = text.lower()
            if "paid" in text_lower and amount_due == 0:
                status = "paid"
            elif "delinquent" in text_lower or "past due" in text_lower:
                status = "delinquent"

            logger.info(f"Parsed tax: Parcel={parcel_number}, Address={address}, Amount=${amount_due}, Year={tax_year}")

            return TaxData(
                parcel_number=parcel_number or search_term,
                address=address,
                tax_year=tax_year,
                amount_due=amount_due,
                due_date=None,
                status=status,
                owner_name=owner_name if owner_name else None,
                raw_data=text[:5000]
            )

        except Exception as e:
            logger.error(f"Failed to parse tax results: {e}")
            return None

    async def scrape_all_taxes(self, identifiers: List[str], search_type: str = "parcel") -> List[TaxData]:
        """
        Scrape tax data for multiple properties.

        Args:
            identifiers: List of parcel numbers or addresses
            search_type: "parcel" or "address"
        """
        results = []

        for identifier in identifiers:
            logger.info(f"Scraping tax {search_type}: {identifier}")

            if search_type == "parcel":
                tax_data = await self.search_tax_by_parcel(identifier)
            else:
                tax_data = await self.search_tax_by_address(identifier)

            if tax_data:
                results.append(tax_data)
                logger.info(f"Found tax: {tax_data.address} - ${tax_data.amount_due} ({tax_data.status})")
            else:
                logger.warning(f"No tax data found for: {identifier}")

            # Rate limiting
            await asyncio.sleep(2)

        return results


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
