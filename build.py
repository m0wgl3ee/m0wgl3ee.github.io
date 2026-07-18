#!/usr/bin/env python3
"""Portfolio site generator.

Workflow for adding a clip:
  1. Add an entry to clips.json (title, url OR file, date, section, pub).
     For a PDF clipping, drop the file in clips/ and set "file": "clips/name.pdf".
  2. Run:  python build.py
     - fetches a thumbnail automatically (YouTube / article og:image / PDF page 1)
     - writes it to img/ and caches the path back into clips.json
     - regenerates index.html
  3. Commit and push.

If a thumbnail can't be fetched, the card falls back to a styled publication
monogram tile. To use a hand-picked image instead, save it in img/ and set
"thumb": "img/whatever.jpg" on the entry.
"""

import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
IMG = ROOT / "img"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}

MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------- thumbnails

def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:48].rstrip("-")


def youtube_id(url: str):
    m = re.search(r"(?:youtu\.be/|youtube\.com/watch\?v=)([\w-]{6,})", url or "")
    return m.group(1) if m else None


def fetch(url: str, binary=False, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def thumb_from_youtube(vid: str) -> str:
    out = IMG / f"yt-{vid}.jpg"
    if not out.exists():
        out.write_bytes(fetch(f"https://img.youtube.com/vi/{vid}/hqdefault.jpg", binary=True))
    return f"img/{out.name}"


def thumb_from_pdf(pdf_path: Path, slug: str) -> str:
    import fitz  # pymupdf
    out = IMG / f"{slug}.png"
    doc = fitz.open(pdf_path)
    page = doc[0]
    w = page.rect.width
    clip = fitz.Rect(0, 0, w, w * 9 / 16)  # top 16:9 slice
    page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), clip=clip).save(out)
    return f"img/{out.name}"


def thumb_from_ogimage(url: str, slug: str):
    page = fetch(url)
    m = (re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', page)
         or re.search(r'<meta[^>]*content="([^"]+)"[^>]*property="og:image"', page))
    if not m:
        return None
    img_url = html.unescape(m.group(1))
    data = fetch(img_url, binary=True, timeout=40)
    ext = ".png" if img_url.lower().split("?")[0].endswith(".png") else \
          ".webp" if img_url.lower().split("?")[0].endswith(".webp") else ".jpg"
    out = IMG / f"{slug}{ext}"
    out.write_bytes(data)
    return f"img/{out.name}"


def resolve_thumb(clip: dict) -> bool:
    """Ensure clip has a usable thumb. Returns True if clips.json changed."""
    if clip.get("no_thumb"):  # site blocks scrapers — use monogram placeholder
        return False
    thumb = clip.get("thumb")
    if thumb and (ROOT / thumb).exists():
        return False
    slug = slugify(clip["title"])
    try:
        if clip.get("file", "").lower().endswith(".pdf"):
            clip["thumb"] = thumb_from_pdf(ROOT / clip["file"], slug)
        elif (vid := youtube_id(clip.get("url", ""))):
            clip["thumb"] = thumb_from_youtube(vid)
        elif clip.get("url"):
            t = thumb_from_ogimage(clip["url"], slug)
            if t:
                clip["thumb"] = t
            else:
                print(f"  ! no og:image for: {clip['title'][:60]}")
                return False
        return clip.get("thumb") is not None
    except Exception as e:
        print(f"  ! thumbnail failed for: {clip['title'][:60]} ({e})")
        return False


# ---------------------------------------------------------------- rendering

def fmt_date(clip: dict) -> str:
    if clip.get("date_label"):
        return clip["date_label"]
    if clip.get("date"):
        y, m, d = (int(x) for x in clip["date"].split("-"))
        return f"{MONTHS[m]} {d}, {y}"
    return ""


def badge_for(clip: dict) -> str:
    if clip.get("file", "").lower().endswith(".pdf"):
        return "PDF"
    if youtube_id(clip.get("url", "")):
        return "▶ VIDEO"
    return ""


def render_card(clip: dict) -> str:
    href = clip.get("file") or clip.get("url", "#")
    badge = badge_for(clip)
    badge_html = f'<span class="badge">{badge}</span>' if badge else ""
    thumb = clip.get("thumb")
    if thumb and (ROOT / thumb).exists():
        thumb_html = (f'<div class="thumb"><img src="{html.escape(thumb)}" alt="" '
                      f'loading="lazy">{badge_html}</div>')
    else:
        thumb_html = (f'<div class="thumb ph"><span>{html.escape(clip["pub"])}</span>'
                      f'{badge_html}</div>')
    meta_date = fmt_date(clip)
    meta = f'<span class="pub">{html.escape(clip["pub"])}</span>'
    if meta_date:
        meta += f" · {html.escape(meta_date)}"
    return f"""      <a class="card" href="{html.escape(href)}" target="_blank" rel="noopener">
        {thumb_html}
        <div class="card-body">
          <h3>{html.escape(clip["title"])}</h3>
          <p class="meta">{meta}</p>
        </div>
      </a>"""


def render_section(section: dict, clips: list) -> str:
    cards = "\n".join(render_card(c) for c in clips)
    return f"""  <section id="{section["id"]}">
    <h2>{html.escape(section["title"])}</h2>
    <p class="section-note">{html.escape(section["note"])}</p>
    <div class="grid">
{cards}
    </div>
  </section>"""


def build(data: dict) -> str:
    p = data["profile"]
    links = "\n      ".join(
        f'<a href="{html.escape(l["url"])}"'
        + ("" if l["url"].startswith("mailto:") else ' target="_blank" rel="noopener"')
        + f'>{html.escape(l["label"])}</a>'
        for l in p["links"])
    nav = "\n    ".join(
        f'<a href="#{s["id"]}">{html.escape(s["title"])}</a>' for s in data["sections"])
    sections = "\n\n".join(
        render_section(s, [c for c in data["clips"] if c["section"] == s["id"]])
        for s in data["sections"])
    return TEMPLATE.format(
        name=html.escape(p["name"]), kicker=html.escape(p["kicker"]),
        bio=html.escape(p["bio"]), email=html.escape(p["email"]),
        links=links, nav=nav, sections=sections, year=date.today().year)


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="{name} — multimedia journalist based in Bangkok, Thailand. Politics, business, and compelling stories for NHK World, AP, Bloomberg and more.">
<title>{name} — Journalist</title>
<style>
  :root {{
    --bg: #0b0f16;           /* blue-black */
    --card: #141b28;
    --card-hover: #18202f;
    --ink: #f2f4f8;
    --ink-soft: #94a1b6;
    --accent: #4d8dff;       /* readable cobalt on dark */
    --accent-deep: #1e4fd8;  /* cobalt fill */
    --accent-soft: rgba(77, 141, 255, 0.14);
    --rule: #222c3e;
    --serif: "Georgia", "Times New Roman", "TH Sarabun New", serif;
    --sans: "Segoe UI", -apple-system, "Helvetica Neue", Arial, sans-serif;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    font-family: var(--sans);
    background: var(--bg);
    color: var(--ink);
    line-height: 1.6;
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 0 1.25rem; }}

  /* ---------- Header ---------- */
  header {{
    padding: 4.5rem 0 3rem;
    border-bottom: 1px solid var(--rule);
    background:
      radial-gradient(ellipse 60% 80% at 85% 10%, rgba(30, 79, 216, 0.22), transparent),
      radial-gradient(ellipse 40% 60% at 10% 90%, rgba(77, 141, 255, 0.08), transparent);
  }}
  .kicker {{
    text-transform: uppercase;
    letter-spacing: 0.18em;
    font-size: 0.75rem;
    color: var(--accent);
    font-weight: 600;
  }}
  h1 {{
    font-family: var(--serif);
    font-size: clamp(2.4rem, 6vw, 3.8rem);
    font-weight: 700;
    line-height: 1.1;
    margin: 0.4rem 0 1rem;
  }}
  .bio {{
    font-family: var(--serif);
    font-size: 1.15rem;
    color: var(--ink-soft);
    max-width: 34em;
  }}
  .links {{
    margin-top: 1.6rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
  }}
  .links a {{
    font-size: 0.85rem;
    font-weight: 600;
    text-decoration: none;
    color: var(--ink);
    border: 1px solid var(--rule);
    border-radius: 999px;
    padding: 0.35rem 0.95rem;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }}
  .links a:hover {{
    border-color: var(--accent);
    color: var(--accent);
    background: var(--accent-soft);
  }}

  /* ---------- Section nav ---------- */
  nav {{
    position: sticky;
    top: 0;
    background: rgba(11, 15, 22, 0.92);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--rule);
    z-index: 10;
  }}
  nav .wrap {{
    display: flex;
    gap: 1.4rem;
    overflow-x: auto;
    padding-top: 0.75rem;
    padding-bottom: 0.75rem;
  }}
  nav a {{
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ink-soft);
    text-decoration: none;
    white-space: nowrap;
  }}
  nav a:hover {{ color: var(--accent); }}

  /* ---------- Sections ---------- */
  section {{ padding: 3.2rem 0 1rem; }}
  h2 {{
    font-family: var(--serif);
    font-size: 1.8rem;
    margin-bottom: 0.35rem;
  }}
  .section-note {{
    color: var(--ink-soft);
    font-size: 0.92rem;
    margin-bottom: 1.6rem;
  }}
  h2::after {{
    content: "";
    display: block;
    width: 3rem;
    height: 3px;
    background: linear-gradient(90deg, var(--accent), var(--accent-deep));
    margin-top: 0.5rem;
    border-radius: 2px;
  }}

  /* ---------- Card grid ---------- */
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 1.2rem;
  }}
  .card {{
    display: flex;
    flex-direction: column;
    background: var(--card);
    border: 1px solid var(--rule);
    border-radius: 10px;
    overflow: hidden;
    text-decoration: none;
    color: var(--ink);
    transition: transform 0.18s, border-color 0.18s, background 0.18s;
  }}
  .card:hover {{
    transform: translateY(-3px);
    border-color: var(--accent);
    background: var(--card-hover);
  }}
  .thumb {{
    position: relative;
    aspect-ratio: 16 / 9;
    background: var(--rule);
    overflow: hidden;
  }}
  .thumb img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }}
  .card:hover .thumb img {{ filter: saturate(1.1) brightness(1.05); }}

  /* placeholder thumbs for clips with no image */
  .thumb.ph {{
    display: flex;
    align-items: center;
    justify-content: center;
    background:
      radial-gradient(ellipse 120% 100% at 0% 0%, rgba(30, 79, 216, 0.55), transparent 65%),
      linear-gradient(145deg, #16233f 0%, #0d1420 100%);
  }}
  .thumb.ph span {{
    font-family: var(--serif);
    font-size: 3rem;
    font-weight: 700;
    color: rgba(77, 141, 255, 0.85);
    letter-spacing: 0.02em;
  }}
  .thumb.ph span.badge {{ font-family: var(--sans); font-size: 0.66rem; }}

  /* play / format badge */
  .badge {{
    position: absolute;
    left: 0.6rem;
    bottom: 0.6rem;
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: #fff;
    background: var(--accent-deep);
    border-radius: 4px;
    padding: 0.15rem 0.5rem;
  }}

  .card-body {{ padding: 0.9rem 1rem 1.05rem; }}
  .card-body h3 {{
    font-family: var(--serif);
    font-size: 1.05rem;
    font-weight: 600;
    line-height: 1.35;
  }}
  .card:hover .card-body h3 {{ color: var(--accent); }}
  .card-body .meta {{
    margin-top: 0.45rem;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--ink-soft);
  }}
  .card-body .meta .pub {{ color: var(--accent); font-weight: 700; }}

  /* ---------- Footer ---------- */
  footer {{
    margin-top: 3.5rem;
    border-top: 1px solid var(--rule);
    padding: 2rem 0 3rem;
    font-size: 0.85rem;
    color: var(--ink-soft);
  }}
  footer a {{ color: var(--accent); text-decoration: none; }}
  footer a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>

<header>
  <div class="wrap">
    <p class="kicker">{kicker}</p>
    <h1>{name}</h1>
    <p class="bio">{bio}</p>
    <div class="links">
      {links}
    </div>
  </div>
</header>

<nav>
  <div class="wrap">
    {nav}
  </div>
</nav>

<main class="wrap">

{sections}

</main>

<footer>
  <div class="wrap">
    <p>© {year} {name} · <a href="mailto:{email}">{email}</a></p>
  </div>
</footer>

</body>
</html>
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp1252
    data = json.loads((ROOT / "clips.json").read_text(encoding="utf-8"))
    IMG.mkdir(exist_ok=True)

    changed = False
    for clip in data["clips"]:
        if resolve_thumb(clip):
            changed = True
            print(f"  ✓ thumbnail: {clip['thumb']}  ({clip['title'][:50]})")

    if changed:
        (ROOT / "clips.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("  ✓ clips.json updated with cached thumbnail paths")

    (ROOT / "index.html").write_text(build(data), encoding="utf-8")
    n = len(data["clips"])
    with_thumb = sum(1 for c in data["clips"]
                     if c.get("thumb") and (ROOT / c["thumb"]).exists())
    print(f"  ✓ index.html generated — {n} clips, "
          f"{with_thumb} with thumbnails, {n - with_thumb} placeholder(s)")


if __name__ == "__main__":
    sys.exit(main())
