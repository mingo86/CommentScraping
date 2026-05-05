"""
Facebook Scraper
Strategia: intercettazione GraphQL + scroll DOM.
Facebook usa GraphQL per caricare i commenti in batch.
"""

import logging
import re
import json
from typing import Optional
from .base_scraper import BaseScraper

logger = logging.getLogger("scraper.facebook")


class FacebookScraper(BaseScraper):
    PLATFORM = "facebook"

    COMMENT_API_PATTERNS = [
        r"facebook\.com/api/graphql",
        r"facebook\.com/ajax/ufi/",
        r"graph\.facebook\.com.*comments",
    ]

    # Keyword nelle variabili GraphQL per identificare query di commenti
    COMMENT_QUERY_NAMES = {
        "CometUFICommentsProviderQuery",
        "CommentsListComponentsPaginationQuery",
        "UFICommentsQuery",
    }

    def _is_comment_endpoint(self, url: str) -> bool:
        return any(re.search(p, url) for p in self.COMMENT_API_PATTERNS)

    def _extract_from_xhr(self, payload: dict) -> list[dict]:
        """
        Facebook GraphQL ha struttura nidificata complessa.
        Naviga ricorsivamente alla ricerca di nodi commento.
        """
        comments = []
        self._recursive_extract(payload, comments)
        return comments

    def _recursive_extract(self, obj, acc: list, depth: int = 0):
        """Ricerca ricorsiva di nodi commento nel payload GraphQL."""
        if depth > 10 or not obj:
            return

        if isinstance(obj, dict):
            # Nodo commento Facebook ha 'body' e 'author'
            if "body" in obj and "text" in obj.get("body", {}):
                text = obj["body"]["text"]
                author = obj.get("author", {})
                if text:
                    acc.append({
                        "id": obj.get("id", f"fb_{len(acc)}"),
                        "text": text,
                        "author": author.get("name", "unknown"),
                        "author_id": author.get("id", ""),
                        "timestamp": obj.get("created_time", ""),
                        "likes": obj.get("feedback", {}).get("reactors", {}).get("count", 0),
                        "element_id": obj.get("id", ""),
                        "platform": self.PLATFORM,
                        "is_reply": False,
                    })
            # Continua esplorazione
            for v in obj.values():
                self._recursive_extract(v, acc, depth + 1)

        elif isinstance(obj, list):
            for item in obj:
                self._recursive_extract(item, acc, depth + 1)

    async def scrape(self, url: str) -> list[dict]:
        """
        Scraping di un post Facebook pubblico.
        Funziona su post di Pagine pubbliche.
        """
        await self._launch()
        collected = []

        try:
            logger.info(f"[Facebook] Navigazione: {url}")
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._page.wait_for_timeout(4000)

            # Dismiss cookie banner
            await self._dismiss_cookie_banner()

            # Expand commenti
            await self._expand_comments()

            # Scroll e raccolta
            await self._infinite_scroll(
                load_more_selector=(
                    'div[aria-label*="comment"] div[role="button"]:has-text("View more"), '
                    'div[role="button"]:has-text("Visualizza altri commenti")'
                ),
                use_xhr=True,
            )

            collected = self._drain_xhr_buffer()

            if not collected:
                collected = await self._dom_fallback()

        finally:
            await self._close()

        logger.info(f"[Facebook] Totale commenti: {len(collected)}")
        return collected

    async def _dismiss_cookie_banner(self):
        for selector in [
            'button[data-cookiebanner="accept_button"]',
            'button[title="Allow all cookies"]',
            'button:has-text("Accept all")',
            'button:has-text("Accetta tutto")',
        ]:
            try:
                btn = self._page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await self._page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

    async def _expand_comments(self):
        """Apri sezione commenti e ordina per "Tutti i commenti"."""
        try:
            # Click su "commenti" se il post è compresso
            comment_btn = self._page.locator(
                'span[data-sigil*="comment-count"], '
                'div[aria-label*="comment"]'
            ).first
            if await comment_btn.is_visible(timeout=3000):
                await comment_btn.click()
                await self._page.wait_for_timeout(2000)
        except Exception:
            pass

    def _drain_xhr_buffer(self) -> list[dict]:
        result = list(self._xhr_buffer)
        self._xhr_buffer.clear()
        return result

    async def _dom_fallback(self) -> list[dict]:
        return await self._page.evaluate("""
            () => {
                const items = [];
                document.querySelectorAll('[data-sigil="comment"], [aria-label*="comment"] [dir="auto"]').forEach((el, i) => {
                    const text = el.innerText?.trim();
                    if (text && text.length > 2) {
                        items.push({
                            id: `fb_dom_${i}`,
                            text,
                            author: 'unknown',
                            timestamp: '',
                            likes: 0,
                            element_id: `fb_dom_${i}`,
                            platform: 'facebook',
                        });
                    }
                });
                return items;
            }
        """)
