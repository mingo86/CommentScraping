"""
Instagram Scraper
Strategia: intercettazione XHR dell'endpoint /api/v1/media/{id}/comments/
+ scroll DOM come fallback.
"""

import logging
import re
from typing import Optional
from .base_scraper import BaseScraper

logger = logging.getLogger("scraper.instagram")


class InstagramScraper(BaseScraper):
    PLATFORM = "instagram"

    # Endpoint API commentI Instagram (app interna)
    COMMENT_API_PATTERNS = [
        r"/api/v1/media/\d+/comments",
        r"www\.instagram\.com/api/v1/media/",
        r"graphql/query.*comment",
    ]

    def _is_comment_endpoint(self, url: str) -> bool:
        return any(re.search(p, url) for p in self.COMMENT_API_PATTERNS)

    def _extract_from_xhr(self, payload: dict) -> list[dict]:
        """
        Parsing del payload JSON dell'API commenti Instagram.
        Struttura: {"comments": [...], "next_min_id": "..."}
        """
        comments = []
        raw = payload.get("comments", [])
        for c in raw:
            text = c.get("text", "")
            if not text:
                continue
            user = c.get("user", {})
            comments.append({
                "id": str(c.get("pk", "")),
                "text": text,
                "author": user.get("username", "unknown"),
                "author_id": str(user.get("pk", "")),
                "timestamp": c.get("created_at_utc", ""),
                "likes": c.get("comment_like_count", 0),
                "element_id": str(c.get("pk", "")),
                "platform": self.PLATFORM,
                "is_reply": c.get("type", 0) == 2,
            })
        return comments

    async def scrape(self, url: str) -> list[dict]:
        """
        Scraping completo di un post Instagram.
        
        Il flusso è:
        1. Apri post
        2. Clicca su commenti se non visibili
        3. Scroll + intercettazione XHR
        4. Raccolta DOM come fallback
        """
        await self._launch()
        collected = []

        try:
            logger.info(f"[Instagram] Navigazione: {url}")
            await self._page.goto(url, wait_until="networkidle", timeout=30000)
            await self._page.wait_for_timeout(3000)

            # Chiudi eventuali popup login
            await self._dismiss_login_popup()

            # Clicca "Visualizza tutti i commenti" se presente
            try:
                view_all = self._page.locator(
                    'span:has-text("Visualizza tutti"), '
                    'span:has-text("View all")'
                ).first
                if await view_all.is_visible(timeout=3000):
                    await view_all.click()
                    await self._page.wait_for_timeout(2000)
            except Exception:
                pass

            # Scroll nel pannello commenti
            await self._scroll_comments_panel()

            # Raccogli da XHR buffer (già popolato durante lo scroll)
            collected = self._drain_xhr_buffer()

            if not collected:
                # Fallback DOM
                logger.info("[Instagram] Fallback DOM extraction")
                collected = await self._dom_fallback()

        finally:
            await self._close()

        logger.info(f"[Instagram] Totale commenti: {len(collected)}")
        return collected

    async def _dismiss_login_popup(self):
        """Chiude popup di login/app se presenti."""
        for selector in [
            'button[aria-label="Close"]',
            'div[role="dialog"] button:has-text("Not Now")',
            'div[role="dialog"] button:has-text("Non ora")',
        ]:
            try:
                btn = self._page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await self._page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

    async def _scroll_comments_panel(self):
        """
        Scrolla il pannello commenti di Instagram.
        Instagram usa un div scrollabile, non window.
        """
        # Selettori per il container commenti
        panel_selectors = [
            'div[class*="comments"] > ul',
            'ul[class*="comments"]',
            'div[role="dialog"] ul',
        ]

        panel = None
        for sel in panel_selectors:
            try:
                el = self._page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    panel = el
                    break
            except Exception:
                pass

        stall_count = 0
        prev_count = 0

        for _ in range(500):  # max 500 scroll
            if len(self._xhr_buffer) >= self.max_comments:
                break

            if panel:
                # Scrolla dentro il panel
                await self._page.evaluate(
                    """(panel) => panel.scrollBy(0, 800)""",
                    await panel.element_handle()
                )
            else:
                await self._page.keyboard.press("End")

            await self._page.wait_for_timeout(self.scroll_pause_ms)

            # Click "Carica altri commenti"
            try:
                more = self._page.locator(
                    'button:has-text("Load more comments"), '
                    'button:has-text("Carica altri commenti"), '
                    'span:has-text("View more comments")'
                ).first
                if await more.is_visible(timeout=500):
                    await more.click()
                    await self._page.wait_for_timeout(1500)
            except Exception:
                pass

            current_count = len(self._xhr_buffer)
            if current_count == prev_count:
                stall_count += 1
                if stall_count >= self.stall_threshold:
                    break
            else:
                stall_count = 0
            prev_count = current_count

    def _drain_xhr_buffer(self) -> list[dict]:
        """Restituisce e svuota il buffer XHR."""
        result = list(self._xhr_buffer)
        self._xhr_buffer.clear()
        return result

    async def _dom_fallback(self) -> list[dict]:
        """Estrazione DOM come backup."""
        return await self._page.evaluate("""
            () => {
                const items = [];
                document.querySelectorAll('ul li[role="menuitem"], div[class*="comment"]').forEach((el, i) => {
                    const text = el.querySelector('span:not([class*="time"])')?.innerText?.trim();
                    const author = el.querySelector('a[href*="instagram.com"]')?.innerText?.trim();
                    if (text && text.length > 1) {
                        items.push({
                            id: `dom_${i}`,
                            text,
                            author: author || 'unknown',
                            timestamp: '',
                            likes: 0,
                            element_id: `dom_${i}`,
                            platform: 'instagram',
                        });
                    }
                });
                return items;
            }
        """)
