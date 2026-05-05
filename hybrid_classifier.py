"""
Hybrid Classifier
Pipeline di classificazione a due livelli:
1. Keyword matching veloce (pre-filtro) — O(1) per commento
2. LLM (Claude API) per i commenti che passano il pre-filtro
   o sono ambigui — alta precisione
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional
import asyncio
import httpx

logger = logging.getLogger("classifier")


# Keyword negativi di default (italiano + inglese)
DEFAULT_NEGATIVE_KEYWORDS = {
    # Insulti / diffamazione
    "idiota", "stupido", "cretino", "imbecille", "deficiente", "scemo",
    "truffatore", "ladro", "bugiardo", "impostore", "fake", "truffa",
    "vergogna", "schifo", "disgustoso", "odio",
    # Minacce
    "ti ammazzo", "ti faccio del male", "ti denuncio", "vi querelo",
    # Inglese
    "scam", "fraud", "liar", "thief", "disgusting", "horrible", "terrible",
    "worst", "awful", "hate", "trash", "garbage", "idiot", "stupid", "moron",
    # Brand damage
    "boicotto", "boicottate", "non comprate", "non acquistate",
    "evitate", "scappate", "truffano", "rubano",
}

# Keyword che indicano contenuto certamente non negativo (skip LLM)
WHITELIST_PATTERNS = [
    r"^\s*❤️|😍|🔥|👏|💯\s*$",  # Solo emoji positive
    r"^(grazie|thank|ottimo|amazing|great|love|bello|fantastico)",
]


class HybridClassifier:
    """
    Classificatore ibrido keyword + Claude API.
    
    Logica:
    - SKIP (non negativo): testo molto breve o solo emoji positive
    - FAST NEGATIVE: contiene keyword inequivocabili → negativo senza LLM
    - LLM CHECK: testo ambiguo o moderatamente sospetto → Claude decide
    - POSITIVE: tutto il resto
    """

    def __init__(
        self,
        keywords_path: Optional[str] = None,
        use_llm: bool = True,
        anthropic_api_key: Optional[str] = None,
        llm_threshold_score: int = 2,  # Score minimo per chiamare LLM
        confidence_threshold: float = 0.7,
    ):
        self.use_llm = use_llm
        self.api_key = anthropic_api_key
        self.llm_threshold_score = llm_threshold_score
        self.confidence_threshold = confidence_threshold

        # Carica keywords
        self.negative_keywords = set(DEFAULT_NEGATIVE_KEYWORDS)
        if keywords_path and Path(keywords_path).exists():
            with open(keywords_path) as f:
                custom = json.load(f)
                self.negative_keywords.update(custom.get("negative", []))

        # Compila regex per performance
        self._keyword_pattern = re.compile(
            r"\b(" + "|".join(re.escape(k) for k in self.negative_keywords) + r")\b",
            re.IGNORECASE
        )
        self._whitelist_patterns = [re.compile(p, re.IGNORECASE) for p in WHITELIST_PATTERNS]

        # Rate limiting per API
        self._semaphore = asyncio.Semaphore(5)  # max 5 LLM calls parallele
        self._llm_calls = 0

        logger.info(
            f"Classifier init: {len(self.negative_keywords)} keywords, "
            f"LLM={'ON' if use_llm else 'OFF'}"
        )

    # ─── Classificazione ───────────────────────────────────────────────────────

    async def classify(self, text: str) -> dict:
        """
        Classifica un commento.
        
        Returns:
            {
                "is_negative": bool,
                "confidence": float,
                "severity": int (1-5),
                "category": str,
                "matched_keywords": list[str],
                "llm_used": bool,
                "reason": str,
            }
        """
        if not text or len(text.strip()) < 2:
            return self._result(False, 0.9, 0, "empty", [], False, "Testo vuoto")

        # 1. Whitelist check (certamente positivo)
        for pat in self._whitelist_patterns:
            if pat.match(text.strip()):
                return self._result(False, 0.95, 0, "positive", [], False, "Whitelist match")

        # 2. Keyword matching
        matches = self._keyword_pattern.findall(text.lower())
        keyword_score = len(set(matches))  # Keyword univoche trovate

        if keyword_score >= 3:
            # Molte keyword → certamente negativo, no LLM needed
            return self._result(
                True, 0.95, min(5, keyword_score + 1), "keyword_strong",
                list(set(matches)), False,
                f"Keyword forti: {', '.join(set(matches))}"
            )

        if keyword_score == 0 and len(text) < 20:
            # Testo corto senza keyword → skip
            return self._result(False, 0.8, 0, "neutral", [], False, "Testo corto neutro")

        # 3. LLM per casi ambigui
        if self.use_llm and (keyword_score >= 1 or len(text) > 30):
            llm_result = await self._classify_with_llm(text, list(set(matches)))
            return llm_result

        # 4. Fallback solo keyword
        is_neg = keyword_score >= 1
        return self._result(
            is_neg,
            0.7 if is_neg else 0.8,
            keyword_score * 2 if is_neg else 0,
            "keyword_weak" if is_neg else "neutral",
            list(set(matches)),
            False,
            f"Keyword match: {', '.join(set(matches))}" if matches else "Nessuna keyword"
        )

    async def _classify_with_llm(self, text: str, keywords_found: list) -> dict:
        """Chiama Claude API per classificazione accurata."""
        async with self._semaphore:
            self._llm_calls += 1
            try:
                result = await self._call_claude(text, keywords_found)
                result["llm_used"] = True
                result["matched_keywords"] = keywords_found
                return result
            except Exception as e:
                logger.warning(f"LLM call failed: {e}, fallback a keyword")
                is_neg = len(keywords_found) > 0
                return self._result(
                    is_neg, 0.6, len(keywords_found) * 2,
                    "keyword_fallback", keywords_found, False,
                    f"LLM error, keyword fallback: {e}"
                )

    async def _call_claude(self, text: str, keywords: list) -> dict:
        """Chiamata diretta all'API Anthropic."""
        system_prompt = """Sei un analista specializzato in brand protection e reputazione online.
Analizza il commento fornito e rispondi SOLO con un JSON valido, senza markdown.

Formato risposta:
{
  "is_negative": bool,
  "confidence": float (0.0-1.0),
  "severity": int (0=neutro, 1=lieve, 2=moderato, 3=grave, 4=molto grave, 5=critico),
  "category": "diffamazione|insulto|minaccia|fake_news|boicottaggio|spam|neutro|positivo",
  "reason": "spiegazione breve in italiano"
}

Considera negativo: insulti diretti, diffamazione, minacce, chiamate al boicottaggio, 
accuse false, contenuti che danneggiano la reputazione del soggetto.
Non considerare negativo: critiche costruttive, feedback negativi sul prodotto,
opinioni normali anche se non positive."""

        user_msg = f'Commento da analizzare: "{text}"'
        if keywords:
            user_msg += f'\n\nKeyword sospette trovate: {", ".join(keywords)}'

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",  # Veloce ed economico per classificazione
                    "max_tokens": 200,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data["content"][0]["text"].strip()
            parsed = json.loads(raw)

            return self._result(
                parsed.get("is_negative", False),
                parsed.get("confidence", 0.8),
                parsed.get("severity", 0),
                parsed.get("category", "neutro"),
                [],  # filled by caller
                True,
                parsed.get("reason", ""),
            )

    @staticmethod
    def _result(
        is_negative: bool,
        confidence: float,
        severity: int,
        category: str,
        keywords: list,
        llm_used: bool,
        reason: str,
    ) -> dict:
        return {
            "is_negative": is_negative,
            "confidence": round(confidence, 3),
            "severity": severity,
            "category": category,
            "matched_keywords": keywords,
            "llm_used": llm_used,
            "reason": reason,
        }

    def stats(self) -> dict:
        return {
            "total_keywords": len(self.negative_keywords),
            "llm_calls_made": self._llm_calls,
        }
