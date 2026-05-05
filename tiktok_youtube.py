"""
TikTok Scraper
Strategia: intercettazione API /aweme/v1/comment/list/ 
TikTok carica i commenti via API JSON paginata.
"""

import logging
import re
from .base_scraper import BaseScraper

logger = logging.getLogger("scraper.tiktok")


class TikTokScraper(BaseScraper):
    PLATFORM = "tiktok"

    COMMENT_API_PATTERNS = [
        r"api\.tiktok\.com/aweme/v1/comment",
        r"api16-normal-c-useast1a\.tiktokv\.com.*comment",
        r"api\.tiktok\.com/api/comment",
        r"comment/list",
    ]

    def _is_comment_endpoint(self, url: str) -> bool:
        return any(re.search(p, url) for p in self.COMMENT_API_PATTERNS)

    def _extract_from_xhr(self, payload: dict) -> list[dict]:
        """
        Payload TikTok: {"comments": [...], "total": N, "has_more": bool}
        """
        comments = []
        for c in payload.get("comments", []) or []:
            text = c.get("text", "")
            if not text:
                continue
            user = c.get("user", {})
            comments.append({
                "id": str(c.get("cid", "")),
                "text": text,
                "author": user.get("unique_id", user.get("nickname", "unknown")),
                "author_id": str(user.get("uid", "")),
                "timestamp": c.get("create_time", ""),
                "likes": c.get("digg_count", 0),
                "reply_count": c.get("reply_comment_total", 0),
                "element_id": str(c.get("cid", "")),
                "platform": self.PLATFORM,
                "is_reply": False,
            })
        return comments

    async def scrape(self, url: str) -> list[dict]:
        await self._launch()
        collected = []

        try:
            logger.info(f"[TikTok] Navigazione: {url}")
            await self._page.goto(url, wait_until="networkidle", timeout=30000)
            await self._page.wait_for_timeout(5000)

            # Apri sezione commenti (click sull'icona)
            try:
                comment_icon = self._page.locator(
                    '[data-e2e="comment-icon"], '
                    'button[aria-label*="comment"], '
                    'span[class*="CommentIcon"]'
                ).first
                if await comment_icon.is_visible(timeout=3000):
                    await comment_icon.click()
                    await self._page.wait_for_timeout(2000)
            except Exception:
                pass

            # Scroll sul pannello commenti
            for _ in range(300):
                if len(self._xhr_buffer) >= self.max_comments:
                    break

                await self._page.evaluate("""
                    () => {
                        const panel = document.querySelector(
                            '[class*="CommentList"], [data-e2e="comment-list"]'
                        );
                        if (panel) panel.scrollBy(0, 600);
                        else window.scrollBy(0, 600);
                    }
                """)
                await self._page.wait_for_timeout(self.scroll_pause_ms)

                prev = len(self._xhr_buffer)
                await self._page.wait_for_timeout(500)
                if len(self._xhr_buffer) == prev:
                    break  # No new data

            collected = list(self._xhr_buffer)
            self._xhr_buffer.clear()

            if not collected:
                collected = await self._dom_fallback()

        finally:
            await self._close()

        logger.info(f"[TikTok] Totale commenti: {len(collected)}")
        return collected

    async def _dom_fallback(self) -> list[dict]:
        return await self._page.evaluate("""
            () => {
                const items = [];
                document.querySelectorAll('[data-e2e="comment-item"], [class*="CommentItem"]').forEach((el, i) => {
                    const text = el.querySelector('[data-e2e="comment-level-1"], p')?.innerText?.trim();
                    const author = el.querySelector('a[href*="/@"]')?.innerText?.trim();
                    if (text) {
                        items.push({
                            id: `tt_dom_${i}`,
                            text,
                            author: author || 'unknown',
                            timestamp: '',
                            likes: 0,
                            element_id: `tt_dom_${i}`,
                            platform: 'tiktok',
                        });
                    }
                });
                return items;
            }
        """)


# ─────────────────────────────────────────────────────────────────────────────


class YouTubeScraper(BaseScraper):
    """
    YouTube Scraper
    YouTube Data API v3 è la soluzione primaria (100% affidabile).
    Lo scraper Playwright è il fallback quando non si ha una API key.
    
    Strategia: intercettazione XHR /youtubei/v1/next (continuation tokens)
    """

    PLATFORM = "youtube"

    COMMENT_API_PATTERNS = [
        r"youtube\.com/youtubei/v1/next",
        r"youtube\.com/youtubei/v1/browse",
    ]

    def __init__(self, api_key: str = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key  # YouTube Data API v3 key (opzionale)

    def _is_comment_endpoint(self, url: str) -> bool:
        return any(re.search(p, url) for p in self.COMMENT_API_PATTERNS)

    def _extract_from_xhr(self, payload: dict) -> list[dict]:
        """
        Il payload di YouTube è molto nidificato.
        I commenti si trovano in continuationItems → commentThreadRenderer.
        """
        comments = []
        self._find_comments_recursive(payload, comments)
        return comments

    def _find_comments_recursive(self, obj, acc: list, depth: int = 0):
        if depth > 15 or not obj:
            return

        if isinstance(obj, dict):
            # Nodo commento
            if "commentRenderer" in obj:
                cr = obj["commentRenderer"]
                runs = cr.get("contentText", {}).get("runs", [])
                text = "".join(r.get("text", "") for r in runs)
                author_runs = cr.get("authorText", {}).get("runs", [])
                author = "".join(r.get("text", "") for r in author_runs)
                if text:
                    acc.append({
                        "id": cr.get("commentId", f"yt_{len(acc)}"),
                        "text": text,
                        "author": author or "unknown",
                        "author_id": cr.get("authorEndpoint", {}).get("browseEndpoint", {}).get("browseId", ""),
                        "timestamp": cr.get("publishedTimeText", {}).get("simpleText", ""),
                        "likes": cr.get("voteCount", {}).get("simpleText", "0"),
                        "element_id": cr.get("commentId", ""),
                        "platform": self.PLATFORM,
                        "is_reply": False,
                    })
            for v in obj.values():
                self._find_comments_recursive(v, acc, depth + 1)

        elif isinstance(obj, list):
            for item in obj:
                self._find_comments_recursive(item, acc, depth + 1)

    async def scrape(self, url: str) -> list[dict]:
        """
        Se disponibile api_key → usa YouTube Data API v3 (molto più efficiente).
        Altrimenti → scraping Playwright.
        """
        if self.api_key:
            return await self._scrape_via_api(url)
        return await self._scrape_via_browser(url)

    async def _scrape_via_api(self, url: str) -> list[dict]:
        """YouTube Data API v3 - nessun limite di lazy loading."""
        import re
        import httpx

        video_id_match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        if not video_id_match:
            logger.error("[YouTube API] Impossibile estrarre video ID")
            return []

        video_id = video_id_match.group(1)
        comments = []
        page_token = None

        async with httpx.AsyncClient() as client:
            while len(comments) < self.max_comments:
                params = {
                    "part": "snippet",
                    "videoId": video_id,
                    "maxResults": 100,
                    "textFormat": "plainText",
                    "key": self.api_key,
                    "order": "relevance",
                }
                if page_token:
                    params["pageToken"] = page_token

                resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/commentThreads",
                    params=params,
                    timeout=10,
                )
                data = resp.json()

                for item in data.get("items", []):
                    snippet = item["snippet"]["topLevelComment"]["snippet"]
                    comments.append({
                        "id": item["id"],
                        "text": snippet.get("textDisplay", ""),
                        "author": snippet.get("authorDisplayName", "unknown"),
                        "author_id": snippet.get("authorChannelId", {}).get("value", ""),
                        "timestamp": snippet.get("publishedAt", ""),
                        "likes": snippet.get("likeCount", 0),
                        "element_id": item["id"],
                        "platform": self.PLATFORM,
                        "is_reply": False,
                    })

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

                logger.info(f"[YouTube API] Raccolti {len(comments)} commenti...")

        return comments

    async def _scrape_via_browser(self, url: str) -> list[dict]:
        """Fallback: scraping browser con scroll."""
        await self._launch()
        collected = []

        try:
            logger.info(f"[YouTube] Navigazione: {url}")
            await self._page.goto(url, wait_until="networkidle", timeout=30000)
            await self._page.wait_for_timeout(5000)

            # Scroll per triggerare caricamento commenti
            for _ in range(3):
                await self._page.evaluate("window.scrollBy(0, 800)")
                await self._page.wait_for_timeout(2000)

            # Scroll continuo
            for _ in range(400):
                if len(self._xhr_buffer) >= self.max_comments:
                    break
                await self._page.evaluate("window.scrollBy(0, 600)")
                await self._page.wait_for_timeout(self.scroll_pause_ms)

            collected = list(self._xhr_buffer)
            self._xhr_buffer.clear()

            if not collected:
                collected = await self._dom_fallback()

        finally:
            await self._close()

        logger.info(f"[YouTube] Totale commenti: {len(collected)}")
        return collected

    async def _dom_fallback(self) -> list[dict]:
        return await self._page.evaluate("""
            () => {
                const items = [];
                document.querySelectorAll('ytd-comment-renderer').forEach((el, i) => {
                    const text = el.querySelector('#content-text')?.innerText?.trim();
                    const author = el.querySelector('#author-text')?.innerText?.trim();
                    const likes = el.querySelector('#vote-count-middle')?.innerText?.trim() || '0';
                    if (text) {
                        items.push({
                            id: `yt_dom_${i}`,
                            text,
                            author: author || 'unknown',
                            timestamp: el.querySelector('.published-time-text a')?.innerText || '',
                            likes: parseInt(likes) || 0,
                            element_id: `yt_dom_${i}`,
                            platform: 'youtube',
                        });
                    }
                });
                return items;
            }
        """)
