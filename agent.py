"""
SocialMonitor Agent - Brand Protection Scraping Agent
Orchestratore principale dell'agente di monitoraggio.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
import argparse

from scrapers.instagram import InstagramScraper
from scrapers.facebook import FacebookScraper
from scrapers.tiktok import TikTokScraper
from scrapers.youtube import YouTubeScraper
from classifiers.hybrid_classifier import HybridClassifier
from reporters.report_generator import ReportGenerator
from utils.config import Config
from utils.logger import setup_logger
from utils.storage import Storage

logger = setup_logger("agent")


class SocialMonitorAgent:
    """
    Agente principale che orchestra scraping, classificazione e reporting.
    """

    def __init__(self, config: Config):
        self.config = config
        self.storage = Storage(config.db_path)
        self.classifier = HybridClassifier(
            keywords_path=config.keywords_path,
            use_llm=config.use_llm,
            anthropic_api_key=config.anthropic_api_key,
        )
        self.reporter = ReportGenerator(config.output_dir)
        self.scrapers = {}

    def _init_scrapers(self):
        """Inizializza i scraper per le piattaforme configurate."""
        scraper_map = {
            "instagram": InstagramScraper,
            "facebook": FacebookScraper,
            "tiktok": TikTokScraper,
            "youtube": YouTubeScraper,
        }
        for platform in self.config.platforms:
            if platform in scraper_map:
                self.scrapers[platform] = scraper_map[platform](
                    proxy=self.config.proxy,
                    headless=self.config.headless,
                    screenshots_dir=self.config.screenshots_dir,
                    max_comments=self.config.max_comments_per_post,
                )
                logger.info(f"✓ Scraper inizializzato: {platform}")

    async def run(self, targets: list[dict]) -> dict:
        """
        Esegue il ciclo completo: scraping → classificazione → report.
        
        Args:
            targets: Lista di {platform, url, profile_name}
        
        Returns:
            Dizionario con statistiche e percorso del report
        """
        self._init_scrapers()
        
        all_negative_comments = []
        stats = {
            "started_at": datetime.now().isoformat(),
            "targets_processed": 0,
            "total_comments_scraped": 0,
            "negative_comments_found": 0,
            "by_platform": {},
        }

        logger.info(f"🚀 Avvio monitoraggio su {len(targets)} target...")

        for target in targets:
            platform = target["platform"].lower()
            url = target["url"]
            profile = target.get("profile_name", url)

            if platform not in self.scrapers:
                logger.warning(f"⚠ Piattaforma non supportata: {platform}")
                continue

            logger.info(f"📡 Scraping {platform} → {profile}")

            try:
                # 1. SCRAPING
                scraper = self.scrapers[platform]
                comments = await scraper.scrape(url)
                logger.info(f"  → {len(comments)} commenti raccolti")

                # 2. CLASSIFICAZIONE
                negative = []
                for comment in comments:
                    result = await self.classifier.classify(comment["text"])
                    if result["is_negative"]:
                        enriched = {
                            **comment,
                            "platform": platform,
                            "profile": profile,
                            "target_url": url,
                            "classification": result,
                        }
                        # Screenshot del commento negativo
                        if comment.get("element_id"):
                            screenshot_path = await scraper.screenshot_comment(
                                comment["element_id"],
                                f"{platform}_{profile}_{comment['id']}"
                            )
                            enriched["screenshot"] = screenshot_path

                        negative.append(enriched)
                        self.storage.save_comment(enriched)

                logger.info(f"  → {len(negative)} commenti negativi trovati")

                # Statistiche
                all_negative_comments.extend(negative)
                stats["targets_processed"] += 1
                stats["total_comments_scraped"] += len(comments)
                stats["negative_comments_found"] += len(negative)
                stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + len(negative)

            except Exception as e:
                logger.error(f"  ✗ Errore su {platform}/{profile}: {e}", exc_info=True)

        # 3. REPORT
        stats["finished_at"] = datetime.now().isoformat()
        logger.info(f"📊 Generazione report ({len(all_negative_comments)} commenti negativi)...")

        report_paths = await self.reporter.generate(
            negative_comments=all_negative_comments,
            stats=stats,
            targets=targets,
        )

        logger.info(f"✅ Report generato:")
        for fmt, path in report_paths.items():
            logger.info(f"   {fmt.upper()}: {path}")

        return {"stats": stats, "reports": report_paths}


async def main():
    parser = argparse.ArgumentParser(description="SocialMonitor Agent")
    parser.add_argument("--config", default="config.json", help="File di configurazione")
    parser.add_argument("--targets", required=True, help="File JSON con i target da monitorare")
    args = parser.parse_args()

    config = Config.from_file(args.config)

    with open(args.targets) as f:
        targets = json.load(f)

    agent = SocialMonitorAgent(config)
    result = await agent.run(targets)

    print("\n" + "=" * 60)
    print("MONITORAGGIO COMPLETATO")
    print("=" * 60)
    print(f"Target processati:      {result['stats']['targets_processed']}")
    print(f"Commenti analizzati:    {result['stats']['total_comments_scraped']}")
    print(f"Commenti negativi:      {result['stats']['negative_comments_found']}")
    print(f"Report CSV:             {result['reports'].get('csv', 'N/A')}")
    print(f"Report PDF:             {result['reports'].get('pdf', 'N/A')}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
