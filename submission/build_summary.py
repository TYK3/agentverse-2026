"""Generate the one-page technical review snapshot; run from any directory."""

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/aftershock-technical-summary.pdf"
STATUS = json.loads((ROOT / "submission/status.json").read_text(encoding="utf-8"))
TEAL = colors.HexColor("#12594f")
INK = colors.HexColor("#172b32")
MUTED = colors.HexColor("#52666b")

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.3, leading=12.3,
                      textColor=INK, spaceAfter=8, alignment=TA_LEFT)
LABEL = ParagraphStyle("label", parent=BODY, fontName="Helvetica-Bold", fontSize=9,
                       leading=12, textColor=TEAL, spaceBefore=10, spaceAfter=6)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.2, leading=10.7, spaceAfter=5)


def paragraph(canvas, text, x, top, width, style=BODY):
    item = Paragraph(text, style)
    _, height = item.wrap(width, 200)
    item.drawOn(canvas, x, top - height)
    return height


def decorate(canvas, doc):
    width, height = A4
    canvas.setFillColor(TEAL)
    canvas.rect(0, height - 130, width, 130, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 29)
    canvas.drawString(40, height - 57, "AFTERSHOCK")
    canvas.setFont("Helvetica", 10.5)
    canvas.drawString(41, height - 80, "Two robots. Evidence before action. A human at the gate.")
    canvas.setFont("Helvetica", 8)
    canvas.drawString(41, height - 108, "AGENTVERSE 2026 / ROBOTICS / TECHNICAL REVIEW SNAPSHOT / 7 NOV 2026")

    canvas.setFillColor(colors.HexColor("#eef4f2"))
    canvas.roundRect(35, 57, width - 70, 137, 6, fill=1, stroke=0)
    paragraph(canvas, "MEASURED DEVELOPMENT EVIDENCE", 47, 180, width - 94, LABEL)
    paragraph(canvas, "<b>42 hub tests + 5 sim tests</b>; live HTTP 200 and typed WebSocket round trip. "
              "Hub PR #47 CI passed; these checks do not establish end-to-end rescue safety.",
              47, 157, width - 94, SMALL)
    paragraph(canvas, "<b>Grid-world safe success: naive 25/30 (83.3%); T12 router 30/30 (100%).</b> "
              "Seeds 0-29, paired layouts; reached with no collapsed cell entered or occupied at collapse.",
              47, 126, width - 94, SMALL)
    paragraph(canvas, "<b>Stand-ins:</b> oracle map, grid dynamics, scripted collapse, test operator, "
              "no MuJoCo verification. Full-system comparison remains pending (#32 / PR #54).",
              47, 94, width - 94, SMALL)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(40, 39, "Sources: docs/brief.md; docs/aftershock.md; coord/CONTRACT.md; PRs #47 and #54.")
    canvas.drawRightString(width - 40, 24, "Review snapshot - final device, latency and submission evidence pending")


def section(story, label, text, style=BODY):
    story.extend([Paragraph(label, LABEL), Paragraph(text, style)])


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUTPUT), pagesize=A4, title="AFTERSHOCK technical summary",
                          author="AFTERSHOCK team", leftMargin=40, rightMargin=40,
                          topMargin=145, bottomMargin=211)
    width, height = A4
    col = (width - 98) / 2
    frames = [Frame(40, 207, col, height - 353, leftPadding=0, rightPadding=0,
                    topPadding=0, bottomPadding=0, id="left"),
              Frame(58 + col, 207, col, height - 353, leftPadding=0, rightPadding=0,
                    topPadding=0, bottomPadding=0, id="right")]
    doc.addPageTemplates(PageTemplate(id="summary", frames=frames, onPage=decorate))
    story = []
    section(story, "01 / USER AND PROBLEM",
            "Search-and-rescue operators need to locate trapped people without sending help into "
            "an unstable route. A second collapse is the critical failure mode: a route that was "
            "clear can become unsafe before the Responder reaches the casualty.")
    section(story, "02 / PERCEIVE, DECIDE, ACT",
            "A light <b>Scout</b> measures the scene with simulated LiDAR, camera, thermal and "
            "acoustic channels. Map cells remain <b>seen, inferred or unknown</b>; only observed "
            "free cells support confirmed movement. Casualties carry positions, confidence and "
            "labelled simulated vitals. A heavier <b>Responder</b> follows verified routes to "
            "deliver supplies and clear only light debris.")
    section(story, "03 / VERIFICATION AND HUMAN CONTROL",
            "<b>Propose &gt; MuJoCo physics check &gt; confidence gate &gt; approval when risky &gt; act.</b> "
            "A rejected route returns to planning. Low confidence sends the Scout to re-look or "
            "refers to a human. An aftershock invalidates the old route and requires fresh evidence. "
            "Risky moves, medical guidance and emergency calls require explicit human approval. "
            "Logs connect observations, physics results and decisions.")
    section(story, "04 / SAFETY LIMITS",
            "No facial identification. Hazard predictions are simulated estimates, not structural "
            "engineering advice. First aid is cited guidance for a person, not diagnosis or autonomous "
            "treatment. This is a prototype of one building, one Scout and one Responder; real rescue "
            "deployment would need hardware and domain validation.")
    story.extend([FrameBreak(), Spacer(1, 0)])
    section(story, "05 / ARCHITECTURE",
            "<b>Sim sensors &gt; perception &gt; planner &gt; sim verification/actions.</b><br/>"
            "One Python process; validated async topic bus. A FastAPI WebSocket sends maps, routes, "
            "reasoning and controls to the console. Sensor frames remain local. Browser writes "
            "are validated; the offline toggle extension is in review.")
    section(story, "06 / MODEL PLACEMENT AND BUDGET",
            "<b>Local CPU:</b> <font face='Courier'>local-astar</font> proposes core routes without "
            "a remote call. MuJoCo runs locally. The development checks used Windows 11 / Python 3.12.<br/><br/>"
            "<b>Cloud features named in the spec:</b><br/>"
            "<font face='Courier'>gemini-4-argon</font> - scene/review<br/>"
            "<font face='Courier'>gemini-3.8-flash</font> - handover<br/>"
            "<font face='Courier'>gemini-3.8-live</font> - commands<br/>"
            "<font face='Courier'>gemini-3.8-flash-tts</font> - speech<br/>"
            "<font face='Courier'>gemini-3.5-live-translate-preview</font><br/>"
            "- casualty translation<br/><br/>"
            "Calls go through <font face='Courier'>coord/gem.py</font>. This snapshot claims no "
            "complete live-model run.<br/><br/>"
            "<b>Offline goal reader:</b> <font face='Courier'>gemma4:e2b</font> (Q4_K_M), "
            "Ollama 0.40.15. T15 reports an 8 GB CPU / WSL2 target, about 4.1 GB model RAM, "
            "1.8-2.8 s warm goal reads and 19 s cold load. Budget limits: 5 GB / 4 s per step. "
            "Source: PR #55 budget.json; its demo uses a scripted physics verdict. "
            "These are lane-reported measurements; <b>final full-system latency is pending.</b>", SMALL)
    section(story, "07 / BEFORE FINAL SUBMISSION",
            "Real-lane evaluation and one continuous demo take with an unscripted obstacle remain "
            "pending. Confirm the Sunday deadline/timezone, capture the final budget, rehearse "
            "the pitch twice and open the pack on a second machine before choosing the demo tag.", SMALL)
    doc.build(story)
    from pypdf import PdfReader
    pages = len(PdfReader(OUTPUT).pages)
    if pages != 1:
        raise ValueError(f"technical summary must be one page, got {pages}")
    print(f"created {OUTPUT} ({pages} page)")


if __name__ == "__main__":
    main()
