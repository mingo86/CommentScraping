# SocialMonitor Agent 🔍
**Brand Protection — Monitoraggio Commenti Negativi**

Agente Python asincrono per il monitoraggio automatico di commenti negativi su
Instagram, Facebook, TikTok e YouTube. Pipeline completa: scraping → classificazione ibrida → report PDF/CSV.

---

## Architettura

```
agent.py                    ← Orchestratore principale
├── scrapers/
│   ├── base_scraper.py     ← Playwright + scroll engine + screenshot
│   ├── instagram.py        ← XHR interception API /api/v1/media/comments
│   ├── facebook.py         ← GraphQL interception
│   └── tiktok_youtube.py   ← API aweme + YouTube Data API v3
├── classifiers/
│   └── hybrid_classifier.py ← Keyword matching + Claude API (claude-haiku)
├── reporters/
│   └── report_generator.py ← CSV + PDF (reportlab)
└── utils/
    ├── config.py           ← Configurazione da JSON + env vars
    ├── logger.py           ← Logging su console + file
    └── storage.py          ← SQLite per persistenza
```

---

## Setup

### 1. Installazione dipendenze

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configurazione

Copia e modifica `config.json`:

```json
{
  "platforms": ["instagram", "facebook", "tiktok", "youtube"],
  "headless": true,
  "proxy": "http://user:pass@host:port",   // opzionale, consigliato
  "max_comments_per_post": 20000,
  "use_llm": true,
  "anthropic_api_key": "sk-ant-...",
  "youtube_api_key": "AIza..."             // opzionale, molto consigliato
}
```

In alternativa, usa variabili d'ambiente:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export YOUTUBE_API_KEY=AIza...
export SCRAPER_PROXY=http://user:pass@host:port
```

### 3. Configura i target

Modifica `targets.json` con i post/video da monitorare:

```json
[
  {
    "platform": "instagram",
    "url": "https://www.instagram.com/p/ABC123/",
    "profile_name": "Mario Rossi"
  },
  {
    "platform": "youtube",
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "profile_name": "Canale di Mario"
  }
]
```

### 4. Avvio

```bash
python agent.py --config config.json --targets targets.json
```

---

## Come funziona lo scraping

### Strategia anti-lazy-loading

```
POST CARICATO
     │
     ├─ 1. XHR Interception (primaria)
     │      Playwright intercetta le risposte di rete
     │      I commenti arrivano direttamente dal JSON API
     │      → Nessun parsing DOM, massima efficienza
     │
     ├─ 2. Scroll Engine
     │      Scroll automatico del pannello commenti
     │      Click su "Carica altri commenti" quando presente
     │      Stall detection: stop se pagina non cambia dopo N tentativi
     │
     └─ 3. DOM Fallback
            Se XHR non produce risultati → parsing diretto del DOM
            Selettori specifici per piattaforma
```

### Per 20.000+ commenti

- YouTube: usa l'API v3 ufficiale (la più efficiente, paginazione nativa)
- Instagram/TikTok: XHR intercept cattura ogni batch di 20-50 commenti
- Facebook: GraphQL batch intercept
- Usa sempre un proxy residenziale per sessioni lunghe

---

## Classificatore Ibrido

```
COMMENTO RICEVUTO
       │
       ├─ Troppo corto o emoji positive? → SKIP (negativo=False)
       │
       ├─ ≥3 keyword negative? → NEGATIVO CERTO (no LLM, veloce)
       │
       ├─ 1-2 keyword o testo lungo? → LLM CHECK (Claude Haiku)
       │      │
       │      └─ {is_negative, severity 0-5, category, reason}
       │
       └─ Nessuna keyword, testo corto → NEUTRO
```

**Costo LLM stimato**: ~$0.01 per 1000 commenti analizzati con Haiku.

---

## Output

### CSV (`output/monitor_TIMESTAMP.csv`)
| Campo | Descrizione |
|-------|-------------|
| platform | instagram/facebook/tiktok/youtube |
| author | Username autore |
| text | Testo commento |
| severity | 0-5 (5=critico) |
| category | diffamazione/insulto/minaccia/... |
| confidence | 0.0-1.0 |
| matched_keywords | Keyword trovate |
| reason | Spiegazione classificazione |
| screenshot | Path immagine screenshot |
| hash_sha256 | Hash per catena di custodia |

### PDF
- Copertina con statistiche generali
- Tabella riepilogativa per piattaforma
- Scheda per ogni commento negativo (ordinati per gravità)
- Screenshot allegati quando disponibili
- Hash SHA-256 per ogni commento (valore probatorio)

---

## Proxy consigliati

Per sessioni lunghe (20k+ commenti) è **fortemente consigliato** un proxy residenziale:
- **Bright Data** — il più affidabile per social media
- **Oxylabs** — ottimo per volumi alti
- **Smartproxy** — buon rapporto qualità/prezzo

---

## Note legali

- ✅ Raccolta dati su profili/pagine pubbliche per legittimo interesse (brand protection)
- ✅ Conservare documentazione del mandato del cliente
- ⚠️ Lo scraping viola i ToS delle piattaforme — usare API ufficiali quando disponibili
- ✅ Hash SHA-256 + timestamp per catena di custodia degli screenshot
- ✅ Definire retention policy per i dati raccolti (GDPR)
- ⚠️ Per uso probatorio in sede legale: valutare marca temporale qualificata eIDAS
