"""
Base Playwright scraper with adaptive multi-strategy extraction.
Handles: Schema.org JSON-LD, OpenGraph, WooCommerce, Shopify, and generic heuristics.
"""
import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

from backend.config import config

logger = logging.getLogger(__name__)


@dataclass
class ScrapedProduct:
    url: str
    source_site: str
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    price_raw: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    sku: Optional[str] = None
    dimensions: Optional[Dict[str, Any]] = None
    weight: Optional[float] = None
    images: List[str] = field(default_factory=list)
    options: List[Dict[str, str]] = field(default_factory=list)
    specs: Dict[str, str] = field(default_factory=dict)
    category: Optional[str] = None
    breadcrumb: Optional[str] = None
    in_stock: Optional[bool] = None
    content_hash: Optional[str] = None
    error: Optional[str] = None

    def compute_hash(self) -> str:
        key = f"{self.title}|{self.price}|{self.model_number}|{self.manufacturer}"
        self.content_hash = hashlib.md5(key.encode("utf-8")).hexdigest()
        return self.content_hash

    def is_valid(self) -> bool:
        return bool(self.title and len(self.title) > 3)


class BaseScraper:
    """
    Playwright-based product scraper.
    Strategy order: JSON-LD → OpenGraph → WooCommerce → Shopify → Generic CSS
    """

    # ----- URL pattern heuristics -----
    PRODUCT_PATH_PATTERNS = [
        r"/product[s]?/[^/]+/?$",
        r"/item[s]?/[^/]+/?$",
        r"/p/[^/]+/?$",
        r"/catalog/product/view",
        r"\bproduct[_-]?id=\d+",
        r"\bpid=\d+",
        r"/shop/[^/]+/[^/]+/?$",
        r"/buy/",
    ]

    NON_PRODUCT_PATHS = [
        "/blog", "/news", "/about", "/contact", "/cart", "/checkout",
        "/account", "/login", "/register", "/privacy", "/terms",
        "/sitemap", "/search", "/tag/", "/author/", "/page/",
        "/wp-admin", "/wp-content", ".css", ".js", ".xml", ".jpg",
        ".png", ".pdf", "/wishlist", "/compare",
    ]

    CATEGORY_PATH_PATTERNS = [
        r"/categor",
        r"/collection[s]?/?$",
        r"/collection[s]?/[^/]+/?$",
        r"/department",
        r"/product-category",
        r"/shop/?$",
        r"/store/?$",
    ]

    # ----- CSS selectors by priority -----
    TITLE_SELECTORS = [
        "h1[itemprop='name']",
        ".product_title",
        "h1.product-title",
        "h1.entry-title",
        ".product-single__title",
        ".product__title h1",
        "h1.page-title",
        "h1",
    ]
    PRICE_SELECTORS = [
        "[itemprop='price']",
        ".woocommerce-Price-amount bdi",
        ".woocommerce-Price-amount",
        ".price ins .amount",
        ".price .amount",
        ".product__price",
        ".price-item--sale",
        ".price-item--regular",
        ".price-current",
        ".sale-price",
        "span.price",
        "[class*='price']:not(script)",
    ]
    DESC_SELECTORS = [
        "[itemprop='description']",
        ".woocommerce-product-details__short-description",
        ".product-description",
        ".product__description",
        "#tab-description",
        ".description .entry-content",
        ".product-summary p",
    ]
    IMAGE_SELECTORS = [
        ".woocommerce-product-gallery__image img",
        "[itemprop='image']",
        ".product-images img",
        ".product__media img",
        ".product-gallery img",
        ".main-image img",
        "#product-image img",
        "img.product-image",
    ]
    STOCK_SELECTORS = [
        ".stock",
        "[class*='stock']",
        ".availability",
        "[itemprop='availability']",
    ]

    def __init__(self, session_id: Optional[int] = None, profile_name: Optional[str] = None):
        self.session_id = session_id
        self.delay: float = config.get("scraping", "delay_between_requests", default=2.0)
        self.max_retries: int = config.get("scraping", "max_retries", default=3)
        self.timeout_ms: int = config.get("scraping", "timeout_seconds", default=30) * 1000
        self.headless: bool = config.get("scraping", "headless", default=True)
        self._consecutive_failures: int = 0
        self._circuit_breaker_threshold: int = config.get("scraping", "circuit_breaker_threshold", default=10)
        self._circuit_breaker_pause: int = config.get("scraping", "circuit_breaker_pause_seconds", default=300)
        self._context_error_count: int = 0

        # Resolve browser profile
        active = profile_name or config.get("browser", "default_profile", default="chrome_mac")
        profiles = config.get("browser", "profiles", default={})
        profile = profiles.get(active, {})
        self._engine: str = profile.get("engine", "chromium")
        self.user_agent: str = profile.get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        self._viewport_width: int = profile.get("viewport_width", 1280)
        self._viewport_height: int = profile.get("viewport_height", 800)
        logger.info("Browser profile: %s (engine=%s)", active, self._engine)

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self) -> "BaseScraper":
        await self.start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.stop()

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        proxy_cfg = None
        if config.get("proxy", "enabled", default=False):
            proxy_cfg = {
                "server": f"http://{config.get('proxy','host')}:{config.get('proxy','port')}",
            }
            if config.get("proxy", "username"):
                proxy_cfg["username"] = config.get("proxy", "username")
                proxy_cfg["password"] = config.get("proxy", "password", default="")

        engine_obj = {
            "chromium": self._playwright.chromium,
            "firefox":  self._playwright.firefox,
            "webkit":   self._playwright.webkit,
        }.get(self._engine, self._playwright.chromium)

        # Chromium accepts many CLI flags; Firefox and WebKit use only a subset
        if self._engine == "chromium":
            launch_kwargs: dict = {
                "headless": self.headless,
                "args": [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            }
        else:
            # Firefox and WebKit do not accept Chromium-specific args
            launch_kwargs = {"headless": self.headless}

        if proxy_cfg:
            launch_kwargs["proxy"] = proxy_cfg

        self._browser = await engine_obj.launch(**launch_kwargs)
        self._context = await self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": self._viewport_width, "height": self._viewport_height},
            ignore_https_errors=True,
            java_script_enabled=True,
        )
        self._context.set_default_timeout(self.timeout_ms)

    async def stop(self) -> None:
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass

    _CONTEXT_ERRORS = ("ERR_INVALID_HANDLE", "ERR_SOCKET_NOT_CONNECTED", "Target page, context or browser has been closed")

    async def _reset_browser(self) -> None:
        """Full Playwright + Chromium restart when the browser process is unrecoverable."""
        logger.warning("Full browser restart — tearing down Playwright and Chromium...")
        await self.stop()
        await asyncio.sleep(2)
        logger.info("Launching fresh Playwright browser instance...")
        await self.start()
        self._context_error_count = 0
        logger.info("Browser restarted successfully.")

    async def _reset_context(self) -> None:
        """Rebuild the browser context. Escalates to full browser restart after 2 consecutive failures."""
        self._context_error_count += 1
        if self._context_error_count >= 2:
            logger.warning(f"Context rebuild failed {self._context_error_count} times — escalating to full browser restart")
            await self._reset_browser()
            return
        logger.warning("Browser context is broken — rebuilding context...")
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        self._context = await self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": self._viewport_width, "height": self._viewport_height},
            ignore_https_errors=True,
            java_script_enabled=True,
        )
        self._context.set_default_timeout(self.timeout_ms)
        logger.info("Browser context rebuilt successfully.")

    async def _new_page(self) -> Page:
        return await self._context.new_page()

    async def _fetch_page(self, url: str, retry: int = 0) -> Optional[Tuple[Page, str]]:
        if self._consecutive_failures >= self._circuit_breaker_threshold:
            logger.warning(
                f"Circuit breaker: {self._consecutive_failures} consecutive failures. "
                f"Pausing {self._circuit_breaker_pause}s to let rate limit reset..."
            )
            self._consecutive_failures = 0
            await asyncio.sleep(self._circuit_breaker_pause)

        page = None
        try:
            page = await self._new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await asyncio.sleep(min(1.5, self.delay))
            html = await page.content()
            await asyncio.sleep(max(0, self.delay - 1.5))
            self._consecutive_failures = 0
            self._context_error_count = 0
            return page, html
        except Exception as exc:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            exc_str = str(exc)
            if any(e in exc_str for e in self._CONTEXT_ERRORS):
                logger.warning(f"Context error on {url}: {exc_str}")
                await self._reset_context()
            if retry < self.max_retries:
                wait = self.delay * (retry + 2)
                logger.warning(f"Retry {retry + 1}/{self.max_retries} for {url}: {exc}")
                await asyncio.sleep(wait)
                return await self._fetch_page(url, retry + 1)
            logger.error(f"Failed {url} after {self.max_retries} retries: {exc}")
            self._consecutive_failures += 1
            return None

    # -----------------------------------------------------------------
    # JSON-LD extraction
    # -----------------------------------------------------------------
    def _extract_json_ld(self, html: str) -> Optional[dict]:
        scripts = re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        for script in scripts:
            try:
                data = json.loads(script.strip())
                candidates = data if isinstance(data, list) else [data]
                for item in candidates:
                    if isinstance(item, dict):
                        if item.get("@type") in ("Product", "IndividualProduct"):
                            return item
                        for graph_item in item.get("@graph", []):
                            if isinstance(graph_item, dict) and graph_item.get("@type") in (
                                "Product", "IndividualProduct"
                            ):
                                return graph_item
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return None

    # -----------------------------------------------------------------
    # Price parsing
    # -----------------------------------------------------------------
    def _parse_price(self, raw: str) -> Optional[float]:
        if not raw:
            return None
        raw = str(raw).strip()
        # Remove currency symbols, keep digits, commas, dots
        cleaned = re.sub(r"[^\d.,]", "", raw)
        if not cleaned:
            return None
        # Handle: 1.234,56 (European) vs 1,234.56 (US)
        if "," in cleaned and "." in cleaned:
            if cleaned.rindex(",") > cleaned.rindex("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned and cleaned.count(",") == 1:
            parts = cleaned.split(",")
            if len(parts[1]) == 2:
                cleaned = cleaned.replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    # -----------------------------------------------------------------
    # Main product extraction
    # -----------------------------------------------------------------
    async def extract_product(self, url: str, source_site: str) -> ScrapedProduct:
        product = ScrapedProduct(url=url, source_site=source_site)
        result = await self._fetch_page(url)
        if not result:
            product.error = "fetch_failed"
            return product

        page, html = result
        try:
            # Strategy 1: JSON-LD Schema.org
            ld = self._extract_json_ld(html)
            if ld:
                product.title = ld.get("name")
                product.description = ld.get("description")
                brand = ld.get("brand")
                if isinstance(brand, dict):
                    product.manufacturer = brand.get("name")
                elif isinstance(brand, str):
                    product.manufacturer = brand
                product.model_number = ld.get("model") or ld.get("mpn")
                product.sku = ld.get("sku") or ld.get("identifier")
                offers = ld.get("offers")
                if isinstance(offers, list) and offers:
                    offers = offers[0]
                if isinstance(offers, dict):
                    product.price = self._parse_price(str(offers.get("price", "")))
                    product.price_raw = str(offers.get("price", ""))
                    avail = offers.get("availability", "")
                    product.in_stock = "InStock" in avail if avail else None
                imgs = ld.get("image", [])
                if isinstance(imgs, str):
                    imgs = [imgs]
                elif isinstance(imgs, dict):
                    imgs = [imgs.get("url", "")]
                product.images = [urljoin(url, i) for i in imgs if i]

            # Strategy 2: OpenGraph
            if not product.title:
                product.title = await self._eval(page, "document.querySelector('meta[property=\"og:title\"]')?.content")
            if not product.images:
                og_img = await self._eval(page, "document.querySelector('meta[property=\"og:image\"]')?.content")
                if og_img:
                    product.images = [og_img]
            if not product.description:
                product.description = await self._eval(page, "document.querySelector('meta[property=\"og:description\"]')?.content")

            # Strategy 3: CSS selectors
            if not product.title:
                product.title = await self._first_text(page, self.TITLE_SELECTORS)

            if not product.price:
                for sel in self.PRICE_SELECTORS:
                    raw = await self._first_text(page, [sel])
                    if raw:
                        p = self._parse_price(raw)
                        if p and p > 0:
                            product.price = p
                            product.price_raw = raw
                            break

            if not product.description:
                product.description = await self._first_text(page, self.DESC_SELECTORS)

            if not product.images:
                images = await self._collect_images(page, url)
                product.images = images

            # Strategy 4: Spec tables
            await self._extract_spec_tables(page, product)

            # Strategy 5: Product options/variants
            await self._extract_options(page, product)

            # Breadcrumb / category
            product.breadcrumb = await self._extract_breadcrumb(page)
            if product.breadcrumb:
                parts = [p.strip() for p in product.breadcrumb.split(">") if p.strip()]
                if len(parts) >= 2:
                    product.category = parts[-2]

            # Normalize image URLs
            product.images = list(dict.fromkeys(
                urljoin(url, img) for img in product.images if img
            ))[:10]

        except Exception as exc:
            logger.error(f"Extraction error for {url}: {exc}")
            product.error = str(exc)
        finally:
            await page.close()

        if product.title:
            product.title = product.title.strip()
        if product.description:
            product.description = product.description.strip()[:5000]

        product.compute_hash()
        return product

    async def _eval(self, page: Page, js: str) -> Optional[str]:
        try:
            result = await page.evaluate(js)
            return str(result).strip() if result else None
        except Exception:
            return None

    async def _first_text(self, page: Page, selectors: List[str]) -> Optional[str]:
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and len(text) > 1:
                        return text
            except Exception:
                continue
        return None

    async def _collect_images(self, page: Page, base_url: str) -> List[str]:
        images = []
        for sel in self.IMAGE_SELECTORS:
            try:
                els = page.locator(sel)
                count = await els.count()
                for i in range(min(count, 6)):
                    src = (
                        await els.nth(i).get_attribute("src")
                        or await els.nth(i).get_attribute("data-src")
                        or await els.nth(i).get_attribute("data-lazy-src")
                    )
                    if src and "placeholder" not in src.lower():
                        images.append(urljoin(base_url, src))
                if images:
                    break
            except Exception:
                continue
        return images

    async def _extract_spec_tables(self, page: Page, product: ScrapedProduct) -> None:
        dimension_keys = {"width", "height", "depth", "length", "diameter", "dimension", "size"}
        weight_keys = {"weight", "lbs", "kg", "pound"}
        manufacturer_keys = {"manufacturer", "brand", "make", "vendor"}
        model_keys = {"model", "mpn", "part number", "model number", "part #"}
        sku_keys = {"sku", "item number", "item #", "item no", "product code"}

        try:
            rows = page.locator("table tr, .specifications li, .product-attributes tr, dl.product-attributes")
            count = await rows.count()
            for i in range(min(count, 50)):
                try:
                    row = rows.nth(i)
                    cells = row.locator("td, th, dt, dd")
                    cell_count = await cells.count()
                    if cell_count >= 2:
                        key = (await cells.nth(0).inner_text()).strip().lower()
                        val = (await cells.nth(1).inner_text()).strip()
                        if not key or not val:
                            continue
                        product.specs[key] = val
                        key_clean = re.sub(r"[^a-z\s]", "", key).strip()
                        if any(k in key_clean for k in dimension_keys):
                            if product.dimensions is None:
                                product.dimensions = {}
                            product.dimensions[key_clean] = val
                        elif any(k in key_clean for k in weight_keys):
                            parsed_w = self._parse_price(val)
                            if parsed_w:
                                product.weight = parsed_w
                        elif any(k in key_clean for k in manufacturer_keys) and not product.manufacturer:
                            product.manufacturer = val
                        elif any(k in key_clean for k in model_keys) and not product.model_number:
                            product.model_number = val
                        elif any(k in key_clean for k in sku_keys) and not product.sku:
                            product.sku = val
                except Exception:
                    continue
        except Exception as exc:
            logger.debug(f"Spec table error: {exc}")

    async def _extract_options(self, page: Page, product: ScrapedProduct) -> None:
        option_selectors = [
            "table.variations tr",
            ".product-form__input",
            "[data-option-index]",
            ".swatch-attribute",
            "select[name*='attribute']",
        ]
        for sel in option_selectors:
            try:
                containers = page.locator(sel)
                count = await containers.count()
                if count == 0:
                    continue
                for i in range(min(count, 10)):
                    container = containers.nth(i)
                    try:
                        label_el = container.locator("label, th, .swatch-attribute-name").first
                        if await label_el.count() > 0:
                            group = (await label_el.inner_text()).strip()
                        else:
                            group = f"Option {i+1}"
                        # Select options
                        options_els = container.locator("option, .swatch-option, .color-swatch")
                        opt_count = await options_els.count()
                        for k in range(opt_count):
                            opt_text = (await options_els.nth(k).inner_text()).strip()
                            opt_val = await options_els.nth(k).get_attribute("value") or opt_text
                            if opt_text and opt_text not in ("", "Select", "Choose an option", "--"):
                                product.options.append({"name": group, "value": opt_text, "sku_suffix": opt_val})
                    except Exception:
                        continue
                if product.options:
                    break
            except Exception:
                continue

    async def _extract_breadcrumb(self, page: Page) -> Optional[str]:
        breadcrumb_selectors = [
            "[itemtype*='BreadcrumbList']",
            ".woocommerce-breadcrumb",
            ".breadcrumb",
            "nav.breadcrumb",
            "[aria-label='breadcrumb']",
            ".breadcrumbs",
        ]
        for sel in breadcrumb_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue
        return None

    # -----------------------------------------------------------------
    # URL discovery
    # -----------------------------------------------------------------
    def _is_product_url(self, url: str, domain: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc and domain not in parsed.netloc:
            return False
        path = (parsed.path + "?" + parsed.query).lower()
        for bad in self.NON_PRODUCT_PATHS:
            if bad in path:
                return False
        for pattern in self.PRODUCT_PATH_PATTERNS:
            if re.search(pattern, path):
                return True
        return False

    def _is_category_url(self, url: str, domain: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc and domain not in parsed.netloc:
            return False
        path = parsed.path.lower()
        for bad in self.NON_PRODUCT_PATHS:
            if bad in path:
                return False
        for pattern in self.CATEGORY_PATH_PATTERNS:
            if re.search(pattern, path):
                return True
        return False

    async def _try_sitemap(self, base_url: str, domain: str) -> List[str]:
        product_urls: List[str] = []
        for sitemap_path in ["/sitemap.xml", "/sitemap_index.xml", "/product-sitemap.xml"]:
            sitemap_url = base_url.rstrip("/") + sitemap_path
            result = await self._fetch_page(sitemap_url)
            if not result:
                continue
            page, html = result
            await page.close()
            locs = re.findall(r"<loc>(.*?)</loc>", html)
            for loc in locs:
                loc = loc.strip()
                if loc.endswith(".xml"):
                    # Sub-sitemap
                    sub_result = await self._fetch_page(loc)
                    if sub_result:
                        sub_page, sub_html = sub_result
                        await sub_page.close()
                        for subloc in re.findall(r"<loc>(.*?)</loc>", sub_html):
                            subloc = subloc.strip()
                            if self._is_product_url(subloc, domain):
                                product_urls.append(subloc)
                elif self._is_product_url(loc, domain):
                    product_urls.append(loc)
            if product_urls:
                break
        return list(dict.fromkeys(product_urls))

    async def discover_product_urls(
        self,
        base_url: str,
        max_pages: int = 200,
        progress_callback=None,
    ) -> List[str]:
        """
        Crawl a site to discover all product URLs.
        Tries sitemap first, then crawls category pages.
        """
        domain = urlparse(base_url).netloc
        visited: set = set()
        product_urls: set = set()

        # Try sitemap first (F02)
        sitemap_urls = await self._try_sitemap(base_url, domain)
        if sitemap_urls:
            logger.info(f"Sitemap found {len(sitemap_urls)} product URLs on {base_url}")
            product_urls.update(sitemap_urls)

        if len(product_urls) >= 10:
            # Good sitemap coverage — skip crawl
            return list(product_urls)

        # Crawl category pages
        to_visit = [base_url]
        pages_visited = 0

        while to_visit and pages_visited < max_pages:
            url = to_visit.pop(0)
            url = url.split("#")[0].rstrip("/")
            if url in visited or not url.startswith("http"):
                continue
            visited.add(url)
            pages_visited += 1

            if progress_callback:
                await progress_callback(
                    event="crawl_progress",
                    data={"pages_visited": pages_visited, "products_found": len(product_urls)},
                )

            result = await self._fetch_page(url)
            if not result:
                continue

            page, html = result
            try:
                all_hrefs = await page.eval_on_selector_all(
                    "a[href]", "els => els.map(e => e.href)"
                )
                for href in all_hrefs:
                    if not href or href in visited:
                        continue
                    href = href.split("#")[0].rstrip("/")
                    if not href.startswith("http"):
                        href = urljoin(url, href)
                    parsed_href = urlparse(href)
                    if domain not in (parsed_href.netloc or ""):
                        continue
                    if self._is_product_url(href, domain):
                        product_urls.add(href)
                    elif self._is_category_url(href, domain) and href not in visited:
                        to_visit.append(href)

                # Follow pagination
                next_url = await self._find_next_page(page, url)
                if next_url and next_url not in visited:
                    to_visit.insert(0, next_url)
            finally:
                await page.close()

        logger.info(f"Discovered {len(product_urls)} product URLs on {base_url}")
        return list(product_urls)

    async def _find_next_page(self, page: Page, current_url: str) -> Optional[str]:
        selectors = [
            "a[rel='next']",
            "a.next",
            ".next a",
            ".pagination a[aria-label='Next']",
            ".pagination-next a",
            "a[aria-label='Next page']",
            ".next-page a",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    href = await el.get_attribute("href")
                    if href and href != current_url:
                        return urljoin(current_url, href)
            except Exception:
                continue
        return None
