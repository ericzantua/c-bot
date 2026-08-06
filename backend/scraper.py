"""Costco.ca product scraper.

Costco fronts its site with bot detection (Akamai). We keep a low profile:
a realistic Chromium user-agent, normal headers, and a delay between requests.
We prefer the embedded JSON-LD Product schema (most stable across redesigns)
and fall back to DOM selectors / meta tags.
"""
import asyncio
import json
import random
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

import config
from models import ProductData

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Chromium flags that reduce automation signals (biggest one: hides
# navigator.webdriver at the browser level).
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
]

# JS injected before page scripts run, to mask common headless/automation tells.
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-CA', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || { runtime: {} };
const _query = window.navigator.permissions && window.navigator.permissions.query;
if (_query) {
  window.navigator.permissions.query = (p) =>
    p && p.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : _query(p);
}
"""

# Signals in the returned HTML that mean we were blocked rather than served a page.
_BLOCK_MARKERS = (
    "access denied",
    "reference #",
    "pardon our interruption",
    "are you a robot",
    "bot detection",
)


class ScrapeError(Exception):
    """Raised with a user-facing message when a product can't be scraped."""


def _product_url(item_code: str) -> str:
    # Costco resolves the bare product id and redirects to the slugged URL.
    return f"{config.COSTCO_BASE}/product.{item_code}.html"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _norm_date(s: str) -> str:
    """MM/DD/YY[YY] -> YYYY-MM-DD (Costco promo dates); pass through if unmatched."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if not m:
        return s.strip()
    mm, dd, yy = m.groups()
    yy = "20" + yy if len(yy) == 2 else yy
    return f"{yy}-{int(mm):02d}-{int(dd):02d}"


def _apply_pricing(html: str, page_text: str, product: ProductData) -> None:
    """Prices from Costco's embedded Next.js data (authoritative).

    JSON-LD's offer price is the REGULAR price, not the sale price, so prefer the
    displayPrice block: onlinePrice = regular, deliveredPrice = current/effective,
    aggregatedDiscountAmt = savings. The sale window comes from the
    'Valid for orders placed MM/DD/YY to MM/DD/YY.' promo statement.
    """
    def cad(v: str) -> str:
        return f"{v} CAD" if v else ""

    cur = reg = None
    disc = 0.0
    m = re.search(
        r'displayPrice[\\":{]*onlinePrice[\\":]*([0-9.]+)[\\",]*'
        r'aggregatedDiscountAmt[\\":]*([0-9.]+)[\\",]*deliveredPrice[\\":]*([0-9.]+)',
        html,
    )
    if m:
        reg, disc, cur = m.group(1), float(m.group(2) or 0), m.group(3)
    else:
        m2 = re.search(r'deliveredPrice[\\":]*([0-9.]+)', html)
        if m2:
            cur = m2.group(1)

    if cur:
        product.price = cad(cur)  # current / effective price (overrides JSON-LD)
        if reg and disc and float(reg) > float(cur):  # on sale
            product.regular_price = cad(reg)
            product.promo_price = cad(cur)  # sale price == current when discounted

    vm = re.search(
        r"Valid for orders?\s+placed\s+[\d/]+\s+to\s+(\d{1,2}/\d{1,2}/\d{2,4})",
        page_text,
    ) or re.search(
        r"Valid for orders?\s+placed\s+[\d/]+\s+to\s+(\d{1,2}/\d{1,2}/\d{2,4})", html
    )
    if vm:
        product.price_valid_until = _norm_date(vm.group(1))


def _parse_json_ld(soup: BeautifulSoup) -> dict:
    """Return the first schema.org Product object found in JSON-LD, if any."""
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _iter_nodes(data):
            if isinstance(node, dict) and _is_product(node):
                return node
    return {}


def _iter_nodes(data):
    """Yield dicts from arbitrarily nested JSON-LD (@graph, lists, etc.)."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)
    elif isinstance(data, dict):
        yield data
        if "@graph" in data:
            yield from _iter_nodes(data["@graph"])


def _is_product(node: dict) -> bool:
    node_type = node.get("@type", "")
    if isinstance(node_type, list):
        return "Product" in node_type
    return node_type == "Product"


def _extract(html: str, item_code: str, url: str) -> ProductData:
    soup = BeautifulSoup(html, "html.parser")
    product = ProductData(item_code=item_code, url=url)

    ld = _parse_json_ld(soup)
    if ld:
        product.title = _clean(ld.get("name", ""))
        brand = ld.get("brand")
        if isinstance(brand, dict):
            product.brand = _clean(brand.get("name", ""))
        elif isinstance(brand, str):
            product.brand = _clean(brand)
        product.description = _clean(ld.get("description", ""))

        offers = ld.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            price = offers.get("price") or offers.get("lowPrice") or ""
            currency = offers.get("priceCurrency", "")
            if price:
                product.price = _clean(f"{price} {currency}".strip())

        rating = ld.get("aggregateRating")
        if isinstance(rating, dict):
            value = rating.get("ratingValue", "")
            count = rating.get("reviewCount") or rating.get("ratingCount") or ""
            if value:
                product.rating = _clean(f"{value} ({count} reviews)" if count else str(value))

    # DOM / meta fallbacks for anything JSON-LD didn't provide.
    if not product.title:
        meta = soup.find("meta", property="og:title")
        h1 = soup.find("h1")
        product.title = _clean(
            (meta.get("content") if meta else "") or (h1.get_text() if h1 else "")
        )
    if not product.description:
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            product.description = _clean(meta.get("content", ""))
    if not product.price:
        price_el = soup.select_one("[automation-id='productPriceOutput'], .price, .your-price")
        if price_el:
            product.price = _clean(price_el.get_text())

    # Bullet-point feature list, commonly rendered as a UL under the product info.
    features: list[str] = []
    for sel in ("#product-details-list li", ".pdp-features li", "[itemprop='description'] li"):
        for li in soup.select(sel):
            txt = _clean(li.get_text())
            if txt and txt not in features:
                features.append(txt)
        if features:
            break
    product.features = features[:20]

    # Costco shows the customer-facing item number + model on a line under the
    # title, e.g. "Item 3118678 | Model B8NVL-678CA". The URL's partNumber is a
    # DIFFERENT internal id, so prefer THIS item number as item_code (that's what
    # customers use), and capture the model. The "|" may be CSS, not text, so it's
    # optional; require Item and Model to be adjacent to avoid false matches.
    page_text = soup.get_text(" ", strip=True)
    combo = re.search(
        r"Item\s+#?\s*(\d{4,})\s*\|?\s*Model\b\s*#?\s*([^\s|]{1,40})", page_text
    )
    if combo:
        product.item_code = combo.group(1)
        product.model = combo.group(2)
    else:
        m_item = re.search(r"\bItem\s+#?\s*(\d{5,})", page_text)
        if m_item:
            product.item_code = m_item.group(1)
        m_model = re.search(r"\bModel\b\s*#?\s*([^\s|]{2,40})", page_text)
        if m_model:
            product.model = m_model.group(1)

    _apply_pricing(html, page_text, product)

    if not product.title:
        raise ScrapeError(
            f"Item {item_code}: page loaded but no product data was found "
            "(item may not exist or the page layout changed)."
        )
    return product


def _looks_blocked(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


async def _open_context(pw):
    """Open a browser context honouring the stealth/channel/headless config.

    Returns (context, closer) where ``closer`` tears everything down.
    """
    # CDP mode: reuse a Chrome you started and cleared yourself. Best vs Akamai.
    if config.CDP_URL:
        browser = await pw.chromium.connect_over_cdp(config.CDP_URL)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()

        async def closer():
            # Leave the user's Chrome running; pages we opened are closed per-scrape.
            return

        return context, closer

    args = _STEALTH_ARGS if config.STEALTH_MODE else []
    ctx_opts = dict(
        user_agent=USER_AGENT,
        locale="en-CA",
        viewport={"width": 1366, "height": 900},
        extra_http_headers={
            "Accept-Language": "en-CA,en;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
        },
    )

    if config.USER_DATA_DIR:
        # Persistent profile: cookies / anti-bot tokens survive across runs.
        context = await pw.chromium.launch_persistent_context(
            config.USER_DATA_DIR,
            headless=config.HEADLESS,
            channel=config.CHROME_CHANNEL or None,
            args=args,
            **ctx_opts,
        )

        async def closer():
            await context.close()

    else:
        browser = await pw.chromium.launch(
            headless=config.HEADLESS,
            channel=config.CHROME_CHANNEL or None,
            args=args,
        )
        context = await browser.new_context(**ctx_opts)

        async def closer():
            await context.close()
            await browser.close()

    if config.STEALTH_MODE:
        await context.add_init_script(_STEALTH_JS)
    return context, closer


async def _warm_up(context) -> None:
    """Visit the homepage first so Akamai's sensor JS issues a clearance cookie
    (_abck / bm_sz) into the (persistent) profile before hitting product pages."""
    try:
        page = await context.new_page()
        await page.goto(config.COSTCO_BASE, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        # Give the sensor time to POST and set the clearance cookie.
        await page.wait_for_timeout(int(random.uniform(2500, 4500)))
        await page.close()
    except Exception:  # noqa: BLE001 - warm-up is best-effort
        pass


async def scrape_products(item_codes: list[str]) -> list[ProductData | ScrapeError]:
    """Scrape each item code, one at a time with a polite (jittered) delay.

    Returns a list aligned with ``item_codes``; each entry is either a
    ``ProductData`` or a ``ScrapeError`` describing what went wrong.
    """
    results: list[ProductData | ScrapeError] = []

    async with async_playwright() as pw:
        context, closer = await _open_context(pw)
        try:
            await _warm_up(context)
            for i, code in enumerate(item_codes):
                code = code.strip()
                if not code:
                    continue
                if i > 0:
                    # Human-like pacing: base delay + up to 1.5s jitter.
                    await asyncio.sleep(config.SCRAPE_DELAY_SECONDS + random.uniform(0, 1.5))
                results.append(await _scrape_one(context, _product_url(code), code))
        finally:
            await closer()

    return results


def _is_product_url(url: str) -> bool:
    return "costco.ca" in url and ("/p/" in url or ".product." in url)


async def scrape_open_tabs() -> list[ProductData | ScrapeError]:
    """Read product data from Costco tabs already open in the CDP Chrome.

    The user navigates to product pages by hand (clearing any Akamai challenge as
    a human); we just read the loaded DOM — no automated navigation to be flagged.
    Requires CDP_URL to point at a Chrome started with --remote-debugging-port.
    """
    if not config.CDP_URL:
        return [
            ScrapeError(
                "CDP_URL is not set. Start Chrome with --remote-debugging-port and "
                "set CDP_URL in .env to read open tabs."
            )
        ]

    results: list[ProductData | ScrapeError] = []
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.connect_over_cdp(config.CDP_URL)
        except Exception as exc:  # noqa: BLE001
            return [
                ScrapeError(
                    f"Could not connect to Chrome at {config.CDP_URL} "
                    f"({type(exc).__name__}). Is the debug Chrome running?"
                )
            ]

        seen: set[str] = set()
        for ctx in browser.contexts:
            for page in ctx.pages:
                url = page.url
                if not _is_product_url(url):
                    continue
                code = _item_code_from_url(url)
                if code in seen:
                    continue
                seen.add(code)
                try:
                    html = await page.content()
                    if _looks_blocked(html):
                        results.append(
                            ScrapeError(f"Tab {code}: shows a bot-check page, not product data.")
                        )
                        continue
                    results.append(_extract(html, code, url))
                except ScrapeError as exc:
                    results.append(exc)
                except Exception as exc:  # noqa: BLE001
                    results.append(ScrapeError(f"Tab {code}: {type(exc).__name__}: {exc}"))

    if not results:
        return [
            ScrapeError(
                "No open costco.ca product tabs found. Open a product page in the "
                "debug Chrome first, then try again."
            )
        ]
    return results


def _item_code_from_url(url: str) -> str:
    """Best-effort item/part identifier from a Costco product URL.

    Costco's canonical URL is /p/-/<slug>/<partNumber>?partNumber=... — the
    part number, not the customer-facing item number. We use partNumber (or the
    last numeric path segment) as a stable id; JSON-LD may override it below.
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if qs.get("partNumber"):
        return qs["partNumber"][0]
    segments = [s for s in parsed.path.split("/") if s]
    for seg in reversed(segments):
        # Match a digit run in the segment: "4000325630" or "product.1858512.html".
        m = re.search(r"\d{5,}", seg)
        if m:
            return m.group(0)
    return segments[-1] if segments else url


async def scrape_urls(urls: list[str]) -> list[ProductData | ScrapeError]:
    """Scrape products from full URLs directly (no item-number → URL guessing)."""
    results: list[ProductData | ScrapeError] = []
    async with async_playwright() as pw:
        context, closer = await _open_context(pw)
        try:
            await _warm_up(context)
            for i, url in enumerate(urls):
                url = url.strip()
                if not url:
                    continue
                if not url.startswith(("http://", "https://")):
                    results.append(ScrapeError(f"'{url}': not a valid http(s) URL."))
                    continue
                if i > 0:
                    await asyncio.sleep(config.SCRAPE_DELAY_SECONDS + random.uniform(0, 1.5))
                results.append(await _scrape_one(context, url, _item_code_from_url(url)))
        finally:
            await closer()
    return results


async def _scrape_one(context, url: str, code: str) -> ProductData | ScrapeError:
    page = await context.new_page()
    try:
        last_block: ScrapeError | None = None
        for attempt in range(2):
            if attempt:  # pause before retry so a fresh clearance cookie can apply
                await page.wait_for_timeout(int(random.uniform(2500, 4500)))
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = response.status if response is not None else 0
            # Let client-rendered content and any anti-bot challenge JS settle.
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:  # noqa: BLE001 - networkidle can time out on busy pages
                pass
            await page.wait_for_timeout(int(random.uniform(800, 1800)))
            html = await page.content()

            if status == 403 or _looks_blocked(html):
                last_block = ScrapeError(
                    f"Item {code}: Costco returned HTTP {status or 403} — blocked by "
                    "bot detection. Retry (a residential IP + visible Chrome helps), "
                    "or use the photo/manual path."
                )
                continue  # retry once
            if status >= 400:
                return ScrapeError(f"Item {code}: Costco returned HTTP {status} (item not found).")
            return _extract(html, code, page.url)
        return last_block
    except ScrapeError as exc:
        return exc
    except Exception as exc:  # noqa: BLE001 - surface any Playwright/timeout error
        msg = str(exc).lower()
        # Akamai often tarpits headless browsers: the request hangs or the HTTP/2
        # stream is reset instead of returning a 403. Report these as blocks.
        if any(s in msg for s in ("timeout", "err_http2", "err_connection", "err_timed_out")):
            return ScrapeError(
                f"Item {code}: request timed out — likely blocked by Costco bot "
                "detection. Try again later or increase SCRAPE_DELAY_SECONDS."
            )
        return ScrapeError(f"Item {code}: failed to scrape ({type(exc).__name__}: {exc}).")
    finally:
        await page.close()
