"""
Base Scraper - Classe base per tutti i scraper di piattaforma.
Gestisce Playwright, proxy, scroll e screenshot.
"""

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger("scraper.base")


class BaseScraper(ABC):
    """
    Classe base con logica comune:
    - Lancio browser Playwright con stealth
    - Gestione proxy
    - Scroll infinito anti-lazy-loading
    - Screenshot di elementi specifici
    - Intercettazione XHR per efficienza
    """

    PLATFORM = "base"

    def __init__(
        self,
        proxy: Optional[str] = None,
        headless: bool = True,
        screenshots_dir: str = "screenshots",
        max_comments: int = 20000,
        scroll_pause_ms: int = 1500,
        stall_threshold: int = 8,
    ):
        self.proxy = proxy
        self.headless = headless
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.max_comments = max_comments
        self.scroll_pause_ms = scroll_pause_ms
        self.stall_threshold = stall_threshold

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        # Buffer per i commenti intercettati via XHR
        self._xhr_buffer: list[dict] = []

    # ─── Lifecycle ─────────────────────────────────────────────────────────────

    async def _launch(self):
        """Lancia il browser con configurazione stealth."""
        self._playwright = await async_playwright().start()

        launch_opts = {
            "headless": self.headless,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
                "--window-size=1920,1080",
            ],
        }
        if self.proxy:
            launch_opts["proxy"] = {"server": self.proxy}

        self._browser = await self._playwright.chromium.launch(**launch_opts)

        context_opts = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "locale": "it-IT",
            "timezone_id": "Europe/Rome",
            "permissions": ["notifications"],
        }
        self._context = await self._browser.new_context(**context_opts)

        # Stealth: rimuovi webdriver flag
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['it-IT', 'it', 'en-US']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = { runtime: {} };
        """)

        self._page = await self._context.new_page()
        await self._setup_xhr_interception()

    async def _close(self):
        """Chiudi tutto."""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ─── XHR Interception ──────────────────────────────────────────────────────

    async def _setup_xhr_interception(self):
        """
        Intercetta le risposte di rete per catturare commenti
        direttamente dal payload API senza parsare il DOM.
        """
        async def on_response(response):
            if not self._is_comment_endpoint(response.url):
                return
            if response.status != 200:
                return
            try:
                body = await response.json()
                extracted = self._extract_from_xhr(body)
                if extracted:
                    self._xhr_buffer.extend(extracted)
                    logger.debug(f"XHR: +{len(extracted)} commenti (tot: {len(self._xhr_buffer)})")
            except Exception:
                pass  # Non tutti gli endpoint sono JSON

        self._page.on("response", on_response)

    @abstractmethod
    def _is_comment_endpoint(self, url: str) -> bool:
        """Override: ritorna True se l'URL è una chiamata API di commenti."""
        pass

    @abstractmethod
    def _extract_from_xhr(self, payload: dict) -> list[dict]:
        """Override: estrae i commenti dal payload JSON intercettato."""
        pass

    # ─── Scroll Engine ─────────────────────────────────────────────────────────

    async def _infinite_scroll(
        self,
        load_more_selector: Optional[str] = None,
        comment_selector: Optional[str] = None,
        use_xhr: bool = True,
    ) -> list[dict]:
        """
        Motore di scroll universale.
        
        Strategie combinate:
        1. Scroll DOM + conteggio elementi (fallback universale)
        2. Intercettazione XHR (primaria, molto più efficiente)
        3. Click su bottoni "Carica altri commenti"
        """
        comments_seen = set()
        stall_count = 0
        scroll_iteration = 0

        while len(comments_seen) < self.max_comments:
            scroll_iteration += 1

            # A) Click "load more" se presente
            if load_more_selector:
                try:
                    btn = self._page.locator(load_more_selector).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        logger.debug(f"Clicked 'load more' (iter {scroll_iteration})")
                        await asyncio.sleep(self.scroll_pause_ms / 1000)
                except Exception:
                    pass

            # B) Scroll to bottom
            prev_height = await self._page.evaluate("document.body.scrollHeight")
            await self._page.evaluate(
                "window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})"
            )
            await asyncio.sleep(self.scroll_pause_ms / 1000)

            # C) Raccolta via XHR buffer (se abilitata)
            if use_xhr and self._xhr_buffer:
                for c in self._xhr_buffer:
                    key = c.get("id") or hashlib.md5(c.get("text", "").encode()).hexdigest()
                    comments_seen.add(key)
                self._xhr_buffer.clear()

            # D) Raccolta via DOM (fallback o complemento)
            if comment_selector:
                dom_comments = await self._extract_dom_comments(comment_selector)
                for c in dom_comments:
                    key = c.get("id") or hashlib.md5(c.get("text", "").encode()).hexdigest()
                    comments_seen.add(key)

            # E) Stall detection
            new_height = await self._page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                stall_count += 1
                logger.debug(f"Stall {stall_count}/{self.stall_threshold} (commenti: {len(comments_seen)})")
                if stall_count >= self.stall_threshold:
                    logger.info(f"Fine scroll: {len(comments_seen)} commenti unici raccolti")
                    break
                await asyncio.sleep(2)
            else:
                stall_count = 0

            if scroll_iteration % 10 == 0:
                logger.info(f"  Scroll iter {scroll_iteration}: ~{len(comments_seen)} commenti")

        return list(comments_seen)

    async def _extract_dom_comments(self, selector: str) -> list[dict]:
        """Estrae commenti dal DOM tramite selettore CSS."""
        try:
            return await self._page.evaluate(f"""
                () => [...document.querySelectorAll('{selector}')]
                    .map((el, idx) => ({{
                        id: el.dataset.id || el.id || `dom_${{idx}}`,
                        text: el.innerText?.trim() || '',
                        element_id: el.dataset.id || el.id || `dom_${{idx}}`,
                    }}))
                    .filter(c => c.text.length > 0)
            """)
        except Exception as e:
            logger.warning(f"DOM extraction error: {e}")
            return []

    # ─── Screenshot ────────────────────────────────────────────────────────────

    async def screenshot_comment(self, element_id: str, filename_base: str) -> Optional[str]:
        """
        Esegue screenshot di un commento specifico con highlight rosso.
        Ritorna il path del file salvato.
        """
        try:
            # Trova elemento per data-id o id
            selector = f'[data-id="{element_id}"], #{element_id}'
            el = self._page.locator(selector).first

            if not await el.is_visible(timeout=3000):
                logger.warning(f"Elemento {element_id} non visibile")
                return None

            # Scrolla in viewport
            await el.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)

            # Highlight
            await self._page.evaluate(f"""
                () => {{
                    const el = document.querySelector('[data-id="{element_id}"], #{element_id}');
                    if (el) {{
                        el.style.outline = '3px solid #e53e3e';
                        el.style.outlineOffset = '4px';
                        el.style.backgroundColor = 'rgba(229, 62, 62, 0.08)';
                        el.style.borderRadius = '6px';
                    }}
                }}
            """)
            await asyncio.sleep(0.3)

            # Screenshot elemento
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in filename_base)
            path = self.screenshots_dir / f"{safe_name}_{ts}.png"
            await el.screenshot(path=str(path))

            # Rimuovi highlight
            await self._page.evaluate(f"""
                () => {{
                    const el = document.querySelector('[data-id="{element_id}"], #{element_id}');
                    if (el) {{
                        el.style.outline = '';
                        el.style.backgroundColor = '';
                    }}
                }}
            """)

            logger.debug(f"Screenshot: {path}")
            return str(path)

        except Exception as e:
            logger.warning(f"Screenshot fallito per {element_id}: {e}")
            return None

    # ─── Public API ────────────────────────────────────────────────────────────

    @abstractmethod
    async def scrape(self, url: str) -> list[dict]:
        """
        Esegue lo scraping completo di una pagina/profilo.
        
        Returns:
            Lista di dict con chiavi: id, text, author, timestamp, likes,
                                      element_id, url, platform
        """
        pass
