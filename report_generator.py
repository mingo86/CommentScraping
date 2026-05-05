"""
Report Generator
Genera report CSV e PDF dai commenti negativi rilevati.
PDF con tabelle, statistiche, screenshot allegati.
"""

import csv
import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("reporter")

# Colori severity (per PDF)
SEVERITY_COLORS = {
    0: (200, 200, 200),   # grigio - neutro
    1: (255, 235, 150),   # giallo chiaro
    2: (255, 200, 100),   # arancione chiaro
    3: (255, 150, 80),    # arancione
    4: (255, 100, 60),    # arancione-rosso
    5: (220, 50, 50),     # rosso
}

CATEGORY_IT = {
    "diffamazione": "Diffamazione",
    "insulto": "Insulto diretto",
    "minaccia": "Minaccia",
    "fake_news": "Notizia falsa",
    "boicottaggio": "Chiamata al boicottaggio",
    "spam": "Spam",
    "keyword_strong": "Keyword sospetta (alta conf.)",
    "keyword_weak": "Keyword sospetta (bassa conf.)",
    "keyword_fallback": "Keyword (fallback)",
    "neutro": "Neutro",
    "positivo": "Positivo",
}


class ReportGenerator:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        negative_comments: list[dict],
        stats: dict,
        targets: list[dict],
    ) -> dict[str, str]:
        """Genera CSV e PDF. Ritorna dict {format: path}."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_id = f"monitor_{ts}"

        paths = {}
        paths["csv"] = self._generate_csv(negative_comments, report_id)
        paths["pdf"] = self._generate_pdf(negative_comments, stats, targets, report_id)
        return paths

    # ─── CSV ──────────────────────────────────────────────────────────────────

    def _generate_csv(self, comments: list[dict], report_id: str) -> str:
        """CSV con tutti i commenti negativi e metadati classificazione."""
        path = self.output_dir / f"{report_id}.csv"

        fieldnames = [
            "id", "platform", "profile", "author", "author_id",
            "text", "timestamp", "likes",
            "severity", "category", "confidence",
            "matched_keywords", "llm_used", "reason",
            "screenshot", "target_url",
            "hash_sha256",
        ]

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()

            for c in sorted(comments, key=lambda x: x.get("classification", {}).get("severity", 0), reverse=True):
                clf = c.get("classification", {})
                text = c.get("text", "")
                row = {
                    "id": c.get("id", ""),
                    "platform": c.get("platform", ""),
                    "profile": c.get("profile", ""),
                    "author": c.get("author", ""),
                    "author_id": c.get("author_id", ""),
                    "text": text,
                    "timestamp": c.get("timestamp", ""),
                    "likes": c.get("likes", 0),
                    "severity": clf.get("severity", 0),
                    "category": CATEGORY_IT.get(clf.get("category", ""), clf.get("category", "")),
                    "confidence": clf.get("confidence", 0),
                    "matched_keywords": ", ".join(clf.get("matched_keywords", [])),
                    "llm_used": clf.get("llm_used", False),
                    "reason": clf.get("reason", ""),
                    "screenshot": c.get("screenshot", ""),
                    "target_url": c.get("target_url", ""),
                    "hash_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
                writer.writerow(row)

        logger.info(f"CSV salvato: {path}")
        return str(path)

    # ─── PDF ──────────────────────────────────────────────────────────────────

    def _generate_pdf(
        self,
        comments: list[dict],
        stats: dict,
        targets: list[dict],
        report_id: str,
    ) -> str:
        """Genera PDF professionale con reportlab."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.lib import colors
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                PageBreak, Image, HRFlowable
            )
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        except ImportError:
            logger.warning("reportlab non installato. Installa con: pip install reportlab")
            return self._generate_pdf_fallback(comments, stats, report_id)

        path = self.output_dir / f"{report_id}.pdf"
        doc = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            rightMargin=2*cm, leftMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )

        styles = getSampleStyleSheet()
        story = []

        # ── Stili personalizzati ──
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Title"],
            fontSize=22,
            textColor=colors.HexColor("#1a1a2e"),
            spaceAfter=6,
        )
        subtitle_style = ParagraphStyle(
            "Subtitle",
            parent=styles["Normal"],
            fontSize=11,
            textColor=colors.HexColor("#555555"),
            spaceAfter=20,
        )
        heading2_style = ParagraphStyle(
            "H2Custom",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#16213e"),
            spaceBefore=16,
            spaceAfter=8,
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#333333"),
        )
        mono_style = ParagraphStyle(
            "Mono",
            parent=styles["Code"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#444444"),
            backColor=colors.HexColor("#f5f5f5"),
        )
        label_style = ParagraphStyle(
            "Label",
            parent=styles["Normal"],
            fontSize=7,
            textColor=colors.HexColor("#888888"),
        )

        # ── Copertina ──
        story.append(Spacer(1, 1*cm))
        story.append(Paragraph("🔍 REPORT BRAND PROTECTION", title_style))
        story.append(Paragraph("Monitoraggio Commenti Negativi — Analisi Automatica", subtitle_style))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#e53e3e")))
        story.append(Spacer(1, 0.5*cm))

        # Info report
        info_data = [
            ["Data generazione:", datetime.now().strftime("%d/%m/%Y %H:%M:%S")],
            ["ID Report:", report_id],
            ["Target monitorati:", str(len(targets))],
            ["Commenti totali analizzati:", str(stats.get("total_comments_scraped", "N/A"))],
            ["Commenti negativi rilevati:", str(stats.get("negative_comments_found", len(comments)))],
        ]
        info_table = Table(info_data, colWidths=[5*cm, 10*cm])
        info_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#666666")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 0.5*cm))

        # ── Statistiche per piattaforma ──
        story.append(Paragraph("Riepilogo per Piattaforma", heading2_style))
        by_platform = stats.get("by_platform", {})
        if by_platform:
            plat_data = [["Piattaforma", "Commenti Negativi", "% sul totale"]]
            total_neg = max(stats.get("negative_comments_found", 1), 1)
            for plat, count in sorted(by_platform.items(), key=lambda x: -x[1]):
                plat_data.append([
                    plat.capitalize(),
                    str(count),
                    f"{count/total_neg*100:.1f}%"
                ])
            plat_table = Table(plat_data, colWidths=[5*cm, 5*cm, 5*cm])
            plat_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8f8f8"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(plat_table)

        # ── Commenti negativi ──
        story.append(PageBreak())
        story.append(Paragraph("Commenti Negativi Rilevati", heading2_style))
        story.append(Paragraph(
            f"I seguenti {len(comments)} commenti sono stati classificati come potenzialmente "
            f"lesivi per la reputazione del soggetto monitorato. Ordinati per gravità decrescente.",
            body_style
        ))
        story.append(Spacer(1, 0.3*cm))

        sorted_comments = sorted(
            comments,
            key=lambda x: x.get("classification", {}).get("severity", 0),
            reverse=True
        )

        for i, c in enumerate(sorted_comments, 1):
            clf = c.get("classification", {})
            severity = clf.get("severity", 0)
            sev_rgb = SEVERITY_COLORS.get(severity, (200, 200, 200))
            sev_color = colors.Color(sev_rgb[0]/255, sev_rgb[1]/255, sev_rgb[2]/255)

            # Header commento
            header_data = [[
                Paragraph(f"#{i} — {c.get('platform','').upper()} | {c.get('profile','')}", body_style),
                Paragraph(
                    f"Gravità: {'★' * severity}{'☆' * (5-severity)} ({severity}/5)",
                    ParagraphStyle("Sev", parent=body_style, alignment=TA_RIGHT)
                ),
            ]]
            header_table = Table(header_data, colWidths=[10*cm, 5*cm])
            header_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), sev_color),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (0, -1), 8),
            ]))
            story.append(header_table)

            # Dettagli
            text = c.get("text", "")
            safe_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            detail_data = [
                ["Autore:", c.get("author", "N/A"), "Data:", c.get("timestamp", "N/A")],
                ["Categoria:", CATEGORY_IT.get(clf.get("category",""), clf.get("category","")),
                 "Confidenza:", f"{clf.get('confidence',0)*100:.0f}%"],
                ["Keyword:", ", ".join(clf.get("matched_keywords", [])) or "—",
                 "LLM:", "✓" if clf.get("llm_used") else "—"],
                ["Motivazione:", clf.get("reason", ""), "", ""],
            ]
            detail_table = Table(detail_data, colWidths=[2.5*cm, 6*cm, 2*cm, 4.5*cm])
            detail_table.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#666666")),
                ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#666666")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (0, -1), 8),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
                ("SPAN", (1, 3), (3, 3)),  # motivazione occupa tutta la riga
            ]))
            story.append(detail_table)

            # Testo commento
            comment_box = Table(
                [[Paragraph(f'"{safe_text}"', mono_style)]],
                colWidths=[15*cm]
            )
            comment_box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f0f0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ]))
            story.append(comment_box)

            # Screenshot se disponibile
            screenshot_path = c.get("screenshot")
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    img = Image(screenshot_path, width=10*cm, height=4*cm)
                    story.append(Spacer(1, 0.2*cm))
                    story.append(img)
                    story.append(Paragraph(f"Screenshot: {os.path.basename(screenshot_path)}", label_style))
                except Exception as e:
                    logger.warning(f"Screenshot non allegabile: {e}")

            # Hash per catena di custodia
            text_hash = hashlib.sha256(text.encode()).hexdigest()
            story.append(Paragraph(f"SHA-256: {text_hash}", label_style))
            story.append(Spacer(1, 0.4*cm))

        doc.build(story)
        logger.info(f"PDF salvato: {path}")
        return str(path)

    def _generate_pdf_fallback(self, comments, stats, report_id) -> str:
        """Fallback HTML→testo se reportlab non disponibile."""
        path = self.output_dir / f"{report_id}_report.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"BRAND PROTECTION REPORT\n")
            f.write(f"Generato: {datetime.now()}\n")
            f.write(f"Commenti negativi: {len(comments)}\n\n")
            for i, c in enumerate(comments, 1):
                clf = c.get("classification", {})
                f.write(f"--- #{i} ---\n")
                f.write(f"Piattaforma: {c.get('platform')}\n")
                f.write(f"Autore: {c.get('author')}\n")
                f.write(f"Gravità: {clf.get('severity')}/5\n")
                f.write(f"Testo: {c.get('text')}\n\n")
        return str(path)
