#!/usr/bin/env python3
"""iF Social Impact Prize — FloodSight 5-page PDF."""
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
import math

W, H = A4  # 595 x 842 pt

# ---- brand ----
INK    = HexColor("#102B3C")   # deep navy
INK2   = HexColor("#33566B")   # muted navy
WATER  = HexColor("#1B7FA8")   # primary blue
WATERL = HexColor("#DCEDF5")   # light wash
MIST   = HexColor("#F3F8FA")   # near-white bg
AMBER  = HexColor("#E8A13D")
RED    = HexColor("#C0392B")
GREEN  = HexColor("#2E7D5B")
WHITE  = HexColor("#FFFFFF")
LINE   = HexColor("#C9DCE6")

F = "/usr/share/fonts/truetype/liberation2/"
pdfmetrics.registerFont(TTFont("Sans", F + "LiberationSans-Regular.ttf"))
pdfmetrics.registerFont(TTFont("SansB", F + "LiberationSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("SansI", F + "LiberationSans-Italic.ttf"))

IMG = "/tmp/ifpdf/"
OUT = "/tmp/ifpdf/FloodSight_iF_Social_Impact_Prize.pdf"

c = canvas.Canvas(OUT, pagesize=A4)
c.setTitle("FloodSight — iF Social Impact Prize entry")
c.setAuthor("Rankine Innovation Lab")
c.setSubject("Open-data flood early warning for Lagos, Nigeria")

M = 46  # page margin

# ---------------------------------------------------------------- helpers
def wrap(text, font, size, width):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if pdfmetrics.stringWidth(t, font, size) <= width:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = w_
    if cur: lines.append(cur)
    return lines

def para(x, y, text, width, font="Sans", size=9.3, leading=13.2, color=INK2):
    c.setFont(font, size); c.setFillColor(color)
    for ln in wrap(text, font, size, width):
        c.drawString(x, y, ln); y -= leading
    return y

def rrect(x, y, w, h, r, fill=None, stroke=None, sw=0.8):
    if fill: c.setFillColor(fill)
    if stroke: c.setStrokeColor(stroke); c.setLineWidth(sw)
    c.roundRect(x, y, w, h, r, stroke=1 if stroke else 0, fill=1 if fill else 0)

def image_card(x, y, w, path, caption=None, cap_w=None):
    """Place image with width w at (x, top y). Returns bottom y."""
    img = ImageReader(IMG + path)
    iw, ih = img.getSize()
    h = w * ih / iw
    c.setStrokeColor(LINE); c.setLineWidth(0.8)
    c.roundRect(x - 4, y - h - 4, w + 8, h + 8, 6, stroke=1, fill=0)
    c.drawImage(img, x, y - h, width=w, height=h)
    yy = y - h - 14
    if caption:
        c.setFont("SansI", 7.8); c.setFillColor(INK2)
        for ln in wrap(caption, "SansI", 7.8, cap_w or w + 8):
            c.drawString(x - 4, yy, ln); yy -= 10
    return yy

def footer(page_no, total=5):
    c.setStrokeColor(LINE); c.setLineWidth(0.7)
    c.line(M, 34, W - M, 34)
    c.setFont("Sans", 7.2); c.setFillColor(INK2)
    c.drawString(M, 23, "FloodSight — Rankine Innovation Lab   |   iF SOCIAL IMPACT PRIZE entry")
    c.drawRightString(W - M, 23, f"{page_no} / {total}")

def header(kicker, title):
    c.setFillColor(WATER); c.rect(M, H - 54, 26, 5, stroke=0, fill=1)
    c.setFont("SansB", 8.6); c.setFillColor(WATER)
    c.drawString(M + 34, H - 53, kicker.upper())
    c.setFont("SansB", 21); c.setFillColor(INK)
    c.drawString(M, H - 80, title)
    return H - 100

def chip(x, y, text, fg=WATER, bg=WATERL, size=7.6, pad=6):
    tw = pdfmetrics.stringWidth(text, "SansB", size)
    rrect(x, y - 4, tw + 2 * pad, 14.5, 7, fill=bg)
    c.setFont("SansB", size); c.setFillColor(fg)
    c.drawString(x + pad, y, text)
    return x + tw + 2 * pad + 6

# ================================================================ PAGE 1
c.setFillColor(INK); c.rect(0, 0, W, H, stroke=0, fill=1)

# subtle contour motif (nested arcs, bottom-right)
c.saveState()
c.setStrokeColor(HexColor("#1A3D52")); c.setLineWidth(1.1)
for i in range(14):
    r = 60 + i * 34
    c.arc(W - 150 - r, -60 - r, W - 150 + r, -60 + r, 20, 140)
c.setStrokeColor(HexColor("#16344699")); c.setLineWidth(0.9)
for i in range(10):
    r = 40 + i * 30
    c.arc(-80 - r, H - 140 - r, -80 + r, H - 140 + r, -60, 80)
c.restoreState()

c.setFillColor(HexColor("#7FBFDB")); c.setFont("SansB", 10.5)
c.drawString(M, H - 92, "iF SOCIAL IMPACT PRIZE  ·  PROJECT DOSSIER")
c.setFillColor(WHITE); c.setFont("SansB", 46)
c.drawString(M, H - 148, "FloodSight")
c.setFont("Sans", 16.5); c.setFillColor(HexColor("#BEDDEB"))
c.drawString(M, H - 176, "Street-level flood early warning for Lagos, Nigeria —")
c.drawString(M, H - 197, "built entirely on free, open data, delivered by SMS.")

y = H - 250
y = para(M, y, "Lagos floods every rainy season. Warnings exist — but they arrive as "
               "state-wide announcements, not as a message that tells a family on a "
               "specific street to move their belongings tonight. FloodSight closes that "
               "last mile: satellites and open data score flood risk for every 200-metre "
               "cell of the city, a live rainfall and tide engine raises Watch and Warning "
               "levels, and residents receive plain-language SMS alerts on any phone — "
               "no smartphone, no app, no data plan.",
         W - 2 * M - 150, font="Sans", size=11, leading=16.5, color=HexColor("#DAE9F1"))

# stat band
sy, sh, gap = 268, 92, 10
sw_ = (W - 2 * M - 3 * gap) / 4
stats = [
    ("15 LGAs", "24,933 cells scored at 200 m — one flood-risk map for the whole city"),
    ("14 / 18", "documented Lagos floods (2011–2024) detected in independent back-testing"),
    ("~ €0", "software cost: 100% open data, open source, free-tier infrastructure"),
    ("1 SMS", "is all it takes to be warned — or to report back what really happened"),
]
for i, (big, small) in enumerate(stats):
    x = M + i * (sw_ + gap)
    rrect(x, sy, sw_, sh, 9, fill=HexColor("#183B50"))
    c.setFillColor(HexColor("#8ECDE8")); c.setFont("SansB", 19.5)
    c.drawString(x + 12, sy + sh - 30, big)
    yy = sy + sh - 46
    c.setFont("Sans", 7.6); c.setFillColor(HexColor("#B9D6E4"))
    for ln in wrap(small, "Sans", 7.6, sw_ - 24):
        c.drawString(x + 12, yy, ln); yy -= 10
# SDG chips
c.setFont("SansB", 8.2); c.setFillColor(HexColor("#7FBFDB"))
c.drawString(M, 236, "CONTRIBUTES TO THE UN SUSTAINABLE DEVELOPMENT GOALS")
x = M
for t in ["SDG 11  Sustainable cities", "SDG 13  Climate action", "SDG 3  Health & well-being", "SDG 1  No poverty"]:
    tw = pdfmetrics.stringWidth(t, "SansB", 8.2)
    rrect(x, 208, tw + 16, 17, 8.5, fill=HexColor("#12455E"))
    c.setFont("SansB", 8.2); c.setFillColor(HexColor("#A8D8EC"))
    c.drawString(x + 8, 213, t)
    x += tw + 24

# applicant block
c.setStrokeColor(HexColor("#2A5065")); c.setLineWidth(0.9)
c.line(M, 150, W - M, 150)
c.setFont("SansB", 9.5); c.setFillColor(WHITE)
c.drawString(M, 128, "Rankine Innovation Lab")
c.setFont("Sans", 8.6); c.setFillColor(HexColor("#B9D6E4"))
c.drawString(M, 113, "Applicant · Lagos, Nigeria")
c.setFont("Sans", 8.6)
c.drawRightString(W - M, 128, "Live system:  floodsight-starter.onrender.com")
c.drawRightString(W - M, 113, "Project page:  www.rankineinnovationlab.com/floodsight.html")
c.setFont("SansI", 8.4); c.setFillColor(HexColor("#7FA8BC"))
c.drawString(M, 78, "Every number in this dossier is reproducible from the project's open codebase and validation logs.")
c.showPage()

# ================================================================ PAGE 2
y = header("The problem", "A megacity that floods every year — and a warning gap")
colw = (W - 2 * M - 24) / 2
xL, xR = M, M + colw + 24

y1 = para(xL, y, "Lagos is a low-lying coastal megacity of more than 15 million people. "
                 "Between 2011 and 2024 it recorded major flood events in nearly every "
                 "rainy season — the 2011 floods alone displaced thousands (NEMA), the "
                 "June 2020 event swept a child away in Orile-Agege, and July 2021 "
                 "brought tidal flooding to Lekki. Flooding is not a surprise here; it "
                 "is a season.", colw)
y1 -= 6
y1 = para(xL, y1, "Yet the warning chain is broken at the last mile. Meteorological "
                  "bulletins are issued state-wide, in technical language, through "
                  "channels — TV, websites, press releases — that rarely reach the "
                  "informal settlements and low-income districts that flood first and "
                  "recover slowest. A resident of Kosofe or Ajegunle typically learns "
                  "of a flood when water enters the house.", colw)
y1 -= 6
y1 = para(xL, y1, "The gap is not data. Elevation, land cover, population, rainfall and "
                  "radar imagery of Lagos are all freely available from public satellite "
                  "programmes. What was missing is the design work that turns that data "
                  "into one clear sentence, delivered to the right street, at the right "
                  "time, on the phones people actually own.", colw)

cap_y = image_card(xR + 4, y - 2, colw - 8,
           "study_area.png",
           "Coverage: 15 flood-prone Local Government Areas of Lagos State (blue), from "
           "Ojo in the west to Ikorodu in the east. Red: Kosofe, the drainage-model pilot.")

# who-it-serves band — placed right below whichever column is longer
by = min(y1, cap_y) - 26
rrect(M, by - 160, W - 2 * M, 160, 10, fill=MIST, stroke=LINE)
c.setFont("SansB", 11.5); c.setFillColor(INK)
c.drawString(M + 16, by - 26, "Designed for the people warnings usually miss")
cols = [
    ("Residents of flood-prone streets", "Plain-language Watch / Warning SMS for their exact location — on any phone. "
     "Subscribing takes one form or one text; leaving takes one word: STOP."),
    ("Community reporters", "After an event, anyone can text FLOOD or NOFLOOD (with a depth, e.g. FLOOD 0.5) "
     "and their report becomes ground truth that retrains the model."),
    ("Emergency agencies (SEMA / LASEMA)", "An operator dashboard shows live alert levels, street-level risk, subscriber "
     "coverage and dispatch history — evidence for pre-positioning response."),
]
cw = (W - 2 * M - 64) / 3
for i, (t, s) in enumerate(cols):
    x = M + 16 + i * (cw + 16)
    c.setFillColor(WATER); c.circle(x + 4, by - 49, 3.2, stroke=0, fill=1)
    yy = by - 53
    c.setFont("SansB", 9.2); c.setFillColor(INK)
    for ln in wrap(t, "SansB", 9.2, cw - 14):
        c.drawString(x + 14, yy, ln); yy -= 11.5
    yy -= 2
    c.setFont("Sans", 8.2); c.setFillColor(INK2)
    for ln in wrap(s, "Sans", 8.2, cw - 6):
        c.drawString(x + 14, yy, ln); yy -= 10.6

# design principles strip
py = by - 186
c.setFont("SansB", 8.6); c.setFillColor(WATER)
c.drawString(M, py, "DESIGN PRINCIPLES")
x = M; py -= 20
for t in ["SMS-first, smartphone-optional", "One message = one segment = one clear action",
          "Calm language, never panic", "Opt-out in every single message", "An explicit ALL CLEAR, not a fade-out"]:
    if x + pdfmetrics.stringWidth(t, "SansB", 7.6) + 18 > W - M:
        x = M; py -= 22
    x = chip(x, py, t)
# timeline of documented flood events used for validation
tl_y = 150
c.setFont("SansB", 8.6); c.setFillColor(WATER)
c.drawString(M, tl_y + 34, "THIRTEEN YEARS OF DOCUMENTED LAGOS FLOODS — THE EVENTS FLOODSIGHT IS TESTED AGAINST")
c.setStrokeColor(LINE); c.setLineWidth(1.2)
c.line(M + 6, tl_y, W - M - 6, tl_y)
events = [("2011", "Jul", RED), ("2012", "Jul", RED), ("2015", "Jul", RED), ("2016", "Jul", RED),
          ("2017", "Jun", RED), ("2018", "Jun", RED), ("2019", "Jul·Oct", RED), ("2020", "Jun", RED),
          ("2021", "Jul ×2", AMBER), ("2022", "Jun·Jul·Oct", RED), ("2023", "Jun·Sep", AMBER), ("2024", "Jun·Jul", RED)]
step = (W - 2 * M - 12) / (len(events) - 1)
for i, (yr, mo, col) in enumerate(events):
    x = M + 6 + i * step
    c.setFillColor(col); c.circle(x, tl_y, 3.4, stroke=0, fill=1)
    c.setFont("SansB", 7.6); c.setFillColor(INK)
    c.drawCentredString(x, tl_y - 16, yr)
    c.setFont("Sans", 6.6); c.setFillColor(INK2)
    c.drawCentredString(x, tl_y - 26, mo)
c.setFont("SansI", 7.6); c.setFillColor(INK2)
c.drawString(M, tl_y - 46, "18 events, sourced from NEMA, LASEMA and FloodList situation reports — replayed against the alert engine as an independent back-test (see page 5).")
footer(2)
c.showPage()

# ================================================================ PAGE 3
y = header("How it works", "Free satellites in, one clear sentence out")

# pipeline diagram
dy, bh = y - 8, 66
bw, gap = (W - 2 * M - 4 * 26) / 5, 26
boxes = [
    ("OPEN DATA", "Copernicus DEM · ESA WorldCover · WorldPop · OSM · Sentinel-1 radar", WATERL, WATER),
    ("RISK MODEL", "Terrain, drainage (HAND) & land cover score all 24,933 cells; SWMM drainage simulation in 3 LGAs", WATERL, WATER),
    ("LIVE SIGNALS", "Rainfall observed + 72-h forecast (GPM, GFS) · sea level / tide (72 h)", WATERL, WATER),
    ("ALERT ENGINE", "Lagos-calibrated thresholds raise per-cell Watch / Warning levels, hourly", HexColor("#FBEEDC"), AMBER),
    ("PEOPLE", "SMS to subscribers at risk · public map · morning briefing · ALL CLEAR when it ends", HexColor("#E7F2EC"), GREEN),
]
for i, (t, s, bg, fg) in enumerate(boxes):
    x = M + i * (bw + gap)
    rrect(x, dy - bh, bw, bh, 8, fill=bg)
    c.setFont("SansB", 8.4); c.setFillColor(fg)
    c.drawString(x + 8, dy - 16, t)
    yy = dy - 28
    c.setFont("Sans", 6.7); c.setFillColor(INK)
    for ln in wrap(s, "Sans", 6.7, bw - 15):
        c.drawString(x + 8, yy, ln); yy -= 8.4
    if i < 4:
        ax = x + bw + 4
        c.setFillColor(INK2)
        c.setFont("SansB", 11)
        c.drawString(ax + 4, dy - bh / 2 - 4, "→")
# feedback loop caption (clean single line under the diagram)
loop_y = dy - bh - 16
c.setStrokeColor(GREEN); c.setLineWidth(1.0); c.setDash(3, 3)
c.line(M + bw / 2, loop_y + 6, W - M - bw / 2, loop_y + 6)
c.setDash()
c.setFont("SansI", 7.8); c.setFillColor(GREEN)
c.drawCentredString(W / 2, loop_y - 6, "and back:  community verification by SMS retrains the model — the loop that makes it more accurate every season")

# susceptibility map hero
iy = loop_y - 30
img_w = 332
cap_y = image_card(M, iy, img_w,
    "suscept_map.png",
    "The city-wide flood susceptibility map: 24,933 cells at 200 m, classified Low to "
    "Very High from elevation, slope, drainage, land cover, distance to water and "
    "population — computed entirely from free satellite data.")

xT = M + img_w + 26
tw_ = W - M - xT
y2 = iy - 4
c.setFont("SansB", 11); c.setFillColor(INK)
c.drawString(xT, y2, "Why open data matters here")
y2 -= 16
y2 = para(xT, y2, "Commercial flood models price out the cities that need them most. "
                  "FloodSight's entire stack — elevation, land cover, population, "
                  "rainfall, radar and tide — is free and global. The result: the "
                  "software cost of protecting a megacity is effectively zero, and the "
                  "same pipeline can be retargeted to Accra, Abidjan or Freetown by "
                  "changing one configuration file.", tw_)
y2 -= 10
c.setFont("SansB", 11); c.setFillColor(INK)
c.drawString(xT, y2, "Physics + learning, honestly labelled")
y2 -= 16
y2 = para(xT, y2, "A transparent, explainable susceptibility model is the backbone. On "
                  "top of it, a hydraulic drainage simulation (SWMM, 6,340 modelled "
                  "junctions across 3 LGAs) and a machine-learning depth model trained "
                  "on 616 satellite-radar-labelled flood observations add street-level "
                  "detail. Every training row carries a provenance label — observed "
                  "vs. simulated — and the public API reports model accuracy only on "
                  "real observations. No black box, no inflated claims.", tw_)
# pull-quote
q_y = 168
c.setFillColor(WATERL); c.rect(M, q_y - 6, 3.2, 30, stroke=0, fill=1)
c.setFont("SansI", 11.4); c.setFillColor(INK)
c.drawString(M + 14, q_y + 10, "Design here is not decoration. It is choosing the 160 characters that stand")
c.drawString(M + 14, q_y - 5, "between a family and a metre of water.")

# open data source chips
sy3 = 96
c.setFont("SansB", 8.6); c.setFillColor(WATER)
c.drawString(M, sy3, "THE OPEN-DATA STACK (ALL FREE, ALL GLOBAL)")
x = M; sy3 -= 20
for t in ["Copernicus DEM", "ESA WorldCover 10 m", "WorldPop", "OpenStreetMap",
          "CHIRPS rainfall", "GPM IMERG satellite rain", "Sentinel-1 SAR",
          "NOAA GFS forecast", "Open-Meteo Marine (tide)"]:
    if x + pdfmetrics.stringWidth(t, "SansB", 7.6) + 18 > W - M:
        x = M; sy3 -= 22
    x = chip(x, sy3, t)
footer(3)
c.showPage()

# ================================================================ PAGE 4
y = header("The experience", "Four text messages that carry a whole service")

# phone mock: chat bubbles
phx, phw = M, 250
pht = y + 6
_phone_patch = True  # panel drawn after bubbles so it hugs the content

def bubble(yy, text, side="in", color=WHITE, label=None):
    bw_ = phw - 44
    lines = wrap(text, "Sans", 8.0, bw_ - 20)
    bh_ = len(lines) * 10.6 + 16
    x = phx + 12 if side == "in" else phx + phw - 12 - bw_
    if label:
        c.setFont("SansB", 6.6); c.setFillColor(INK2)
        c.drawString(x + 6, yy - 8, label.upper()); yy -= 12
    rrect(x, yy - bh_, bw_, bh_, 8, fill=color, stroke=LINE, sw=0.6)
    ty = yy - 14
    c.setFont("Sans", 8.0); c.setFillColor(INK)
    for ln in lines:
        c.drawString(x + 10, ty, ln); ty -= 10.6
    return yy - bh_ - 9

_bub = []
def bubble_defer(*a, **k):
    _bub.append((a, k))
yy = pht - 26
yy = bubble(yy, "FloodSight: Flood Watch for Kosofe. Heavy rain expected - avoid "
                "flood-prone streets. Map: rankineinnovationlab.com/floodsight "
                "Reply STOP to opt out", label="Day 1 · 08:00")
yy = bubble(yy, "FloodSight ALERT: Flood Warning for Kosofe. Avoid low roads. Move to "
                "higher ground if needed. Reply STOP to opt out",
            color=HexColor("#FDEBE7"), label="Day 1 · 14:00")
yy = bubble(yy, "FLOOD 0.5", side="out", color=HexColor("#DFF0E7"),
            label="resident replies · day 2")
yy = bubble(yy, "FloodSight: All clear for Kosofe. Flood alert has ended. Stay careful "
                "near drains and canals. Reply STOP to opt out",
            color=HexColor("#E7F2EC"), label="Day 2 · 09:00")
phb = yy - 8

xT = M + phw + 26
tw_ = W - M - xT
y2 = y - 2
items = [
    ("Every message is engineered", 
     "Alerts fit a single GSM-7 SMS segment (≤160 characters) so they cost one "
     "message on every Nigerian network, always name the recipient's area, always "
     "carry the opt-out — verified by automated tests on every release."),
    ("The conversation goes both ways",
     "Replying STOP unsubscribes instantly; START re-joins. Texting FLOOD 0.5 or "
     "NOFLOOD files a geo-referenced field report against that day's alerts — "
     "residents become the sensor network that audits and retrains the system."),
    ("An honest ending",
     "When conditions pass, subscribers get an explicit ALL CLEAR. Alerts that "
     "simply stop breed alarm fatigue; a stand-down message builds the trust an "
     "early-warning service lives on."),
    ("Privacy by design (NDPR)",
     "Explicit consent at sign-up, optional SMS-code confirmation so nobody can be "
     "subscribed (or moved) without holding the phone, PII visible only to "
     "authorized operators, and a 12-month data-retention policy."),
    ("What it costs to run",
     "The only marginal cost of the whole service is the SMS itself: NGN 5-15 "
     "(under 2 euro-cents) per message via Africa's Talking. Hosting, data and "
     "models run on free tiers - the service scales with need, not with budget."),
]
for t, s in items:
    c.setFillColor(WATER); c.circle(xT + 3, y2 - 3.4, 3.0, stroke=0, fill=1)
    c.setFont("SansB", 10.2); c.setFillColor(INK)
    c.drawString(xT + 13, y2 - 7, t)
    y2 -= 21
    y2 = para(xT + 13, y2, s, tw_ - 13, size=8.6, leading=12.2)
    y2 -= 9

# subscriber journey band
jy = 218
c.setFont("SansB", 8.6); c.setFillColor(WATER)
c.drawString(M, jy + 30, "ONE SUBSCRIBER'S JOURNEY")
steps4 = [("Subscribe", "web form or SMS", WATER), ("Confirm", "6-digit code (OTP)", WATER),
          ("Watch", "rain approaching", AMBER), ("Warning", "act now", RED),
          ("All clear", "explicit stand-down", GREEN), ("Report", "text FLOOD or DRY", WATER)]
jw = (W - 2 * M - 5 * 14) / 6
for i, (t, sub, col) in enumerate(steps4):
    x = M + i * (jw + 14)
    rrect(x, jy - 26, jw, 40, 7, fill=MIST, stroke=LINE)
    c.setFillColor(col); c.circle(x + 11, jy + 1, 3.0, stroke=0, fill=1)
    c.setFont("SansB", 8.4); c.setFillColor(INK)
    c.drawString(x + 19, jy - 2, t)
    c.setFont("Sans", 6.6); c.setFillColor(INK2)
    c.drawString(x + 8, jy - 16, sub)
    if i < 5:
        c.setFont("SansB", 9); c.setFillColor(INK2)
        c.drawString(x + jw + 3.5, jy - 4, "→")

# draw the phone panel behind the bubbles (redraw pass)
rrect(phx, phb, phw, pht - phb, 14, stroke=LINE)
c.setFillColor(LINE); c.rect(phx + phw/2 - 25, pht - 14, 50, 4, stroke=0, fill=1)

# early traction strip
ty2 = 116
rrect(M, ty2 - 46, W - 2 * M, 58, 9, fill=WATERL)
c.setFont("SansB", 9.2); c.setFillColor(WATER)
c.drawString(M + 14, ty2 - 8, "WHERE THE PILOT STANDS TODAY")
para(M + 14, ty2 - 23,
     "Live city-wide system  ·  daily 06:00 SMS briefing  ·  hourly alert dispatch  ·  "
     "first resident cohort (8 subscribers) onboarded ahead of the 2026 rainy season  ·  "
     "field-verification loop open and waiting for its first season of ground truth.",
     W - 2 * M - 28, size=8.6, leading=12.5, color=INK)
footer(4)
c.showPage()

# ================================================================ PAGE 5
y = header("Evidence & ambition", "Validated against 13 years of real Lagos floods")

colw = (W - 2 * M - 24) / 2
xL, xR = M, M + colw + 24

cap_y = image_card(xL, y - 2, colw - 8,
    "validation_bars.png",
    "Independent back-test: replaying 2011–2023 rainfall against FloodSight's "
    "thresholds. Across the full 18-event register (2011–2024) the system flags "
    "14 of 18 documented Lagos floods (78%). The misses cluster in dam-release and "
    "data-artefact events — which is exactly what the roadmap addresses next.")

y2 = y - 2
c.setFont("SansB", 11); c.setFillColor(INK)
c.drawString(xR, y2, "Measurable results")
y2 -= 15
for t in ["14 / 18 historical Lagos floods (2011–2024) correctly flagged in back-testing",
          "Satellite-radar cross-check: SWMM drainage hotspots overlap observed 2024 flood extents",
          "616 radar-labelled flood-depth observations from two real events anchor the ML layer",
          "Every alert, dispatch and field report is logged — precision & recall are recomputed after every event"]:
    c.setFillColor(GREEN)
    c.circle(xR + 3, y2 + 2.6, 2.6, stroke=0, fill=1)
    yy = y2
    c.setFont("Sans", 8.4); c.setFillColor(INK2)
    for ln in wrap(t, "Sans", 8.4, colw - 16):
        c.drawString(xR + 12, yy, ln); yy -= 10.8
    y2 = yy - 4
y2 -= 4
rrect(xR, y2 - 74, colw, 78, 8, fill=MIST, stroke=LINE)
c.setFont("SansB", 9.6); c.setFillColor(INK)
c.drawString(xR + 10, y2 - 12, "A different kind of claim: radical honesty")
para(xR + 10, y2 - 26,
     "Every training example is labelled observed vs. simulated, and the public API "
     "reports accuracy only on real observations — including where the model is "
     "still weak. In a field crowded with overstated “AI”, an early-warning "
     "system earns trust by publishing what it cannot yet do.",
     colw - 20, size=8.2, leading=11.4)

# roadmap + what funding does
ry = 368
c.setFont("SansB", 11.5); c.setFillColor(INK)
c.drawString(M, ry, "What the iF Social Impact Prize would fund")
ry -= 10
steps = [
    ("2026 rainy season", "Full-season pilot across 15 LGAs: SMS credits for thousands of residents (≈ €0.12 per resident per season) and stipends for community verification reporters."),
    ("Close the misses", "Integrate Oyan dam releases and NiHSA tide-gauge data — the two flood drivers rainfall alone cannot see — with agency partnerships."),
    ("Prove, then scale", "Publish season precision/recall openly; retarget the one-config-file pipeline to a second West African coastal city with a local partner."),
]
sw2 = (W - 2 * M - 40) / 3
for i, (t, s) in enumerate(steps):
    x = M + i * (sw2 + 20)
    c.setFillColor(WATER); c.setFont("SansB", 15)
    c.drawString(x, ry - 22, f"{i+1}")
    c.setFont("SansB", 9.4); c.setFillColor(INK)
    yy = ry - 22
    for ln in wrap(t, "SansB", 9.4, sw2 - 22):
        c.drawString(x + 16, yy, ln); yy -= 11.5
    yy -= 2
    c.setFont("Sans", 8.0); c.setFillColor(INK2)
    for ln in wrap(s, "Sans", 8.0, sw2):
        c.drawString(x, yy, ln); yy -= 10.4

# criteria mapping band
cy = 178
rrect(M, 60, W - 2 * M, cy - 60, 9, fill=INK)
c.setFont("SansB", 9.4); c.setFillColor(HexColor("#8ECDE8"))
c.drawString(M + 14, cy - 18, "IN THE LANGUAGE OF THE FIVE iF CRITERIA")
rows = [
    ("Solves a problem", "closes the last-mile warning gap for a flooding megacity"),
    ("Moral-ethical standards", "consent, opt-out, privacy, calm language, honest metrics"),
    ("Connection to design", "the product IS design: information design of one 160-character sentence"),
    ("Effort vs. use value", "open data + free infrastructure → a city protected for the cost of its SMS"),
    ("Positive experience", "two-way dialogue, an explicit all-clear, residents as partners not recipients"),
]
yy = cy - 34
for t, s in rows:
    c.setFont("SansB", 8.0); c.setFillColor(WHITE)
    c.drawString(M + 14, yy, t)
    c.setFont("Sans", 8.0); c.setFillColor(HexColor("#B9D6E4"))
    c.drawString(M + 150, yy, "—  " + s)
    yy -= 13.6

# contact
c.setFont("Sans", 7.8); c.setFillColor(INK2)
c.drawString(M, 44, "Contact: Habeeb Adegoke · Rankine Innovation Lab · ahadegok@asu.edu · floodsight-starter.onrender.com · www.rankineinnovationlab.com/floodsight.html")
footer(5)
c.showPage()

c.save()
print("PDF written:", OUT)
