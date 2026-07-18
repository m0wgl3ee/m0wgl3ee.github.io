#!/usr/bin/env python3
"""Portfolio site generator — filing-cabinet layout.

Workflow for adding a clip:
  1. Add an entry to clips.json (title, url OR file, date, section, pub,
     topic/topics, summary).
     For a PDF clipping, drop the file in clips/ and set "file": "clips/name.pdf".
  2. Run:  python build.py
     - fetches a thumbnail automatically (YouTube / article og:image / PDF page 1)
     - writes it to img/ and caches the path back into clips.json
     - regenerates index.html
  3. Commit and push — GitHub Pages redeploys automatically.

If a thumbnail can't be fetched, the card falls back to a styled publication
monogram tile. To use a hand-picked image instead, save it in img/ and set
"thumb": "img/whatever.jpg" on the entry. Set "no_thumb": true to stop the
build from retrying a blocked fetch every run (Bloomberg needs this).
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

OUTLET_ORDER = ["nhk", "ap", "freelance", "bloomberg"]  # most recent first


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
    # Wayback/print saves carry a print header + archive banner + site nav at
    # the top — start the crop below that chrome so the headline leads
    y0 = w * 0.20 if "Wayback Machine" in page.get_text()[:300] else 0
    clip = fitz.Rect(0, y0, w, y0 + w * 9 / 16)  # 16:9 slice
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

def fmt_date(clip):
    if clip.get("date_label"):
        return clip["date_label"]
    if clip.get("date"):
        y, m, d = (int(x) for x in clip["date"].split("-"))
        return f"{MONTHS[m]} {d}, {y}"
    return ""


def badge_for(clip):
    if clip.get("file", "").lower().endswith(".pdf"):
        return "PDF"
    if youtube_id(clip.get("url", "")):
        return "▶ VIDEO"
    return ""


def clip_topics(clip):
    return clip.get("topics") or ([clip["topic"]] if clip.get("topic") else [])


def render_card(clip, show_pub):
    href = clip.get("file") or clip.get("url", "#")
    badge = badge_for(clip)
    badge_html = f'<span class="badge">{badge}</span>' if badge else ""
    summary = clip.get("summary", "")
    summary_html = (f'<div class="summary"><p>{html.escape(summary)}</p></div>'
                    if summary else "")
    thumb = clip.get("thumb")
    if thumb and (ROOT / thumb).exists():
        inner = f'<img src="{html.escape(thumb)}" alt="" loading="lazy">'
        ph = ""
    else:
        inner = f'<span class="mono">{html.escape(clip["pub"])}</span>'
        ph = " ph"
    meta = f'<span class="pub">{html.escape(clip["pub"])}</span>' if show_pub else ""
    d = fmt_date(clip)
    if d:
        meta += (" · " if meta else "") + html.escape(d)
    return f"""          <a class="card" href="{html.escape(href)}" target="_blank" rel="noopener">
            <div class="thumb{ph}">{inner}{badge_html}{summary_html}</div>
            <div class="card-body">
              <h3>{html.escape(clip["title"])}</h3>
              <p class="meta">{meta}</p>
            </div>
          </a>"""


def render_tab(group, fid, title, count, active):
    cls = "tab active" if active else "tab"
    return (f'<button class="{cls}" data-group="{group}" data-id="{fid}" '
            f'onclick="openFolder(\'{group}\',\'{fid}\')">'
            f'{html.escape(title)}<span class="count">{count}</span></button>')


def render_panel(group, fid, note, cards, active):
    hidden = "" if active else " hidden"
    return f"""      <section class="panel" data-group="{group}" data-id="{fid}"{hidden}>
        <p class="folder-note">{html.escape(note)}</p>
        <div class="grid">
{chr(10).join(cards)}
        </div>
      </section>"""


def build(data: dict) -> str:
    p = data["profile"]
    sections = {s["id"]: s for s in data["sections"]}

    outlet_tabs, outlet_panels = [], []
    for i, sid in enumerate(OUTLET_ORDER):
        s = sections[sid]
        clips = [c for c in data["clips"] if c["section"] == sid]
        cards = [render_card(c, show_pub=False) for c in clips]
        outlet_tabs.append(render_tab("outlet", sid, s["title"], len(clips), i == 0))
        outlet_panels.append(render_panel("outlet", sid, s["note"], cards, i == 0))

    topic_tabs, topic_panels = [], []
    first = True
    for t in data.get("topics", []):
        clips = [c for c in data["clips"] if t["id"] in clip_topics(c)]
        if not clips:
            continue
        clips.sort(key=lambda c: c.get("date", ""), reverse=True)
        cards = [render_card(c, show_pub=True) for c in clips]
        topic_tabs.append(render_tab("topic", t["id"], t["title"], len(clips), first))
        # topic panels all start hidden — Outlet is the default view; setView()
        # reveals the first topic panel when the user switches
        topic_panels.append(render_panel("topic", t["id"], t["note"], cards, False))
        first = False

    links = "\n        ".join(
        f'<a href="{html.escape(l["url"])}"'
        + ("" if l["url"].startswith("mailto:") else ' target="_blank" rel="noopener"')
        + f'>{html.escape(l["label"])}</a>'
        for l in p["links"])

    return TEMPLATE.format(
        name=html.escape(p["name"]), kicker=html.escape(p["kicker"]),
        bio=html.escape(p["bio"]), email=html.escape(p["email"]), links=links,
        outlet_tabs="\n      ".join(outlet_tabs),
        topic_tabs="\n      ".join(topic_tabs),
        outlet_panels="\n\n".join(outlet_panels),
        topic_panels="\n\n".join(topic_panels),
        year=date.today().year)


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="{name} — multimedia journalist based in Bangkok, Thailand. Politics, business, and compelling stories for NHK World, AP, Bloomberg and more.">
<title>{name} — Journalist</title>
<style>
  :root {{
    --bg: #0b0f16;
    --card: #10182a;
    --card-hover: #16203a;
    --ink: #f2f4f8;
    --ink-soft: #94a1b6;
    --accent: #4d8dff;
    --accent-deep: #1e4fd8;
    --accent-soft: rgba(77, 141, 255, 0.14);
    --rule: #222c3e;
    --folder: #151d30;
    --folder-edge: #2a3854;
    --tab-idle: #101725;
    --serif: "Georgia", "Times New Roman", "TH Sarabun New", serif;
    --sans: "Segoe UI", -apple-system, "Helvetica Neue", Arial, sans-serif;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  [hidden] {{ display: none !important; }}
  html, body {{ height: 100%; }}
  body {{
    font-family: var(--sans);
    background: var(--bg);
    color: var(--ink);
    line-height: 1.5;
    display: flex;
    overflow: hidden;
  }}

  /* ---------- Left rail ---------- */
  aside {{
    width: 300px;
    flex: none;
    display: flex;
    flex-direction: column;
    padding: 2.2rem 1.7rem 1.6rem;
    border-right: 1px solid var(--rule);
    background:
      radial-gradient(ellipse 100% 45% at 0% 0%, rgba(30, 79, 216, 0.20), transparent),
      radial-gradient(ellipse 80% 40% at 100% 100%, rgba(77, 141, 255, 0.06), transparent);
    overflow-y: auto;
  }}
  .kicker {{
    text-transform: uppercase; letter-spacing: 0.16em;
    font-size: 0.7rem; color: var(--accent); font-weight: 600;
  }}
  h1 {{
    font-family: var(--serif);
    font-size: 2.1rem;
    font-weight: 700;
    line-height: 1.12;
    margin: 0.35rem 0 0.8rem;
  }}
  .bio {{ font-family: var(--serif); color: var(--ink-soft); font-size: 0.97rem; line-height: 1.55; }}
  .links {{ display: flex; flex-wrap: wrap; gap: 0.45rem; margin-top: 1.1rem; }}
  .links a {{
    font-size: 0.78rem; font-weight: 600; text-decoration: none; color: var(--ink);
    border: 1px solid var(--rule); border-radius: 999px; padding: 0.25rem 0.8rem;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }}
  .links a:hover {{ border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }}

  .toolbar {{ margin-top: 1.6rem; }}
  .toolbar .label {{
    display: block;
    font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.1em;
    color: var(--ink-soft); margin-bottom: 0.5rem;
  }}
  .toggle {{
    font: inherit; font-size: 0.8rem; font-weight: 600; color: var(--ink-soft);
    background: none; border: 1px solid var(--rule); border-radius: 999px;
    padding: 0.28rem 0.95rem; cursor: pointer; margin-right: 0.35rem;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }}
  .toggle:hover {{ color: var(--accent); border-color: var(--accent); }}
  .toggle.active {{ color: #fff; background: var(--accent-deep); border-color: var(--accent-deep); }}

  .rail-foot {{
    margin-top: auto;
    padding-top: 1.4rem;
    font-size: 0.72rem;
    color: var(--ink-soft);
  }}
  .rail-foot a {{ color: var(--accent); text-decoration: none; }}

  /* ---------- Cabinet fills the rest ---------- */
  main {{
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    padding: 1.5rem 1.6rem 1.4rem;
  }}
  .cabinet {{
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }}
  .tabs {{
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 3px;
    padding: 0 0.9rem;
    position: relative;
    z-index: 3;
  }}
  .tab {{
    font: inherit;
    font-size: 0.76rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: var(--ink-soft);
    background: var(--tab-idle);
    border: 1px solid var(--rule);
    border-bottom: none;
    border-radius: 9px 9px 0 0;
    padding: 0.4rem 0.9rem 0.5rem;
    margin-bottom: -1px;
    cursor: pointer;
    clip-path: polygon(7px 0, calc(100% - 7px) 0, 100% 100%, 0 100%);
    transition: background 0.15s, color 0.15s, padding 0.15s;
  }}
  .tab:hover {{ color: var(--accent); background: var(--card-hover); }}
  .tab.active {{
    color: var(--ink);
    background: var(--folder);
    border-color: var(--folder-edge);
    padding-top: 0.55rem;
    padding-bottom: 0.65rem;
  }}
  .tab .count {{
    display: inline-block;
    margin-left: 0.45rem;
    font-size: 0.64rem;
    font-weight: 700;
    color: var(--accent);
    background: var(--accent-soft);
    border-radius: 999px;
    padding: 0.05rem 0.42rem;
  }}

  .folder {{
    position: relative;
    z-index: 2;
    flex: 1;
    min-height: 0;
    display: flex;
  }}
  .folder::before, .folder::after {{
    content: "";
    position: absolute;
    left: 10px; right: 10px; top: -7px;
    height: 20px;
    background: var(--tab-idle);
    border: 1px solid var(--rule);
    border-radius: 12px 12px 0 0;
    z-index: -1;
  }}
  .folder::after {{
    left: 22px; right: 22px; top: -13px;
    background: #0d1420;
  }}
  .panel {{
    flex: 1;
    min-width: 0;
    background: var(--folder);
    border: 1px solid var(--folder-edge);
    border-radius: 12px;
    padding: 1rem 1.1rem 1.1rem;
    box-shadow: 0 18px 40px rgba(0, 0, 0, 0.45);
    animation: pull 0.22s ease-out;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--folder-edge) transparent;
  }}
  @keyframes pull {{
    from {{ transform: translateY(8px); opacity: 0.4; }}
    to   {{ transform: translateY(0);   opacity: 1; }}
  }}
  .folder-note {{ color: var(--ink-soft); font-size: 0.82rem; margin: 0 0.15rem 0.8rem; }}

  /* ---------- Cards ---------- */
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
    gap: 1rem;
  }}
  .card {{
    display: flex;
    flex-direction: column;
    background: var(--card);
    border: 1px solid var(--rule);
    border-radius: 9px;
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
  .thumb {{ position: relative; aspect-ratio: 16 / 9; background: var(--rule); overflow: hidden; }}
  .thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .thumb.ph {{
    display: flex; align-items: center; justify-content: center;
    background:
      radial-gradient(ellipse 120% 100% at 0% 0%, rgba(30, 79, 216, 0.55), transparent 65%),
      linear-gradient(145deg, #16233f 0%, #0d1420 100%);
  }}
  .thumb.ph .mono {{ font-family: var(--serif); font-size: 2.2rem; font-weight: 700; color: rgba(77, 141, 255, 0.85); }}
  .badge {{
    position: absolute; left: 0.5rem; bottom: 0.5rem; z-index: 1;
    font-size: 0.6rem; font-weight: 700; letter-spacing: 0.08em; color: #fff;
    background: var(--accent-deep); border-radius: 4px; padding: 0.12rem 0.42rem;
  }}
  .summary {{
    position: absolute; inset: 0; z-index: 2;
    display: flex; align-items: center;
    padding: 0.65rem 0.8rem;
    background: rgba(11, 15, 22, 0.9);
    opacity: 0; transition: opacity 0.18s;
  }}
  .summary p {{
    font-size: 0.85rem; line-height: 1.5; color: var(--ink);
    display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden;
  }}
  .card:hover .summary, .card:focus-visible .summary {{ opacity: 1; }}
  @media (hover: none) {{ .summary {{ display: none; }} }}

  .card-body {{ padding: 0.75rem 0.9rem 0.9rem; }}
  .card-body h3 {{
    font-family: var(--serif); font-size: 1.05rem; font-weight: 600; line-height: 1.32;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
  }}
  .card:hover .card-body h3 {{ color: var(--accent); }}
  .card-body .meta {{
    margin-top: 0.35rem; font-size: 0.7rem;
    text-transform: uppercase; letter-spacing: 0.07em; color: var(--ink-soft);
  }}
  .card-body .meta .pub {{ color: var(--accent); font-weight: 700; }}

  /* ---------- Small screens: fall back to stacked, scrollable ---------- */
  @media (max-width: 900px) {{
    body {{ display: block; overflow: auto; height: auto; }}
    aside {{
      width: auto;
      border-right: none;
      border-bottom: 1px solid var(--rule);
      padding: 1.6rem 1.25rem 1.3rem;
    }}
    .rail-foot {{ display: none; }}
    main {{ padding: 1.2rem 1rem 2rem; }}
    .panel {{ overflow: visible; }}
  }}
</style>
</head>
<body>

<aside>
  <span class="kicker">{kicker}</span>
  <h1>{name}</h1>
  <p class="bio">{bio}</p>
  <div class="links">
        {links}
  </div>
  <div class="toolbar">
    <span class="label">File by</span>
    <button class="toggle active" id="btn-outlet" onclick="setView('outlet')">Outlet</button>
    <button class="toggle" id="btn-topic" onclick="setView('topic')">Topic</button>
  </div>
  <div class="rail-foot">
    <p>© {year} {name}<br><a href="mailto:{email}">{email}</a></p>
  </div>
</aside>

<main>
  <div class="cabinet">
    <div class="tabs" id="tabs-outlet">
      {outlet_tabs}
    </div>
    <div class="tabs" id="tabs-topic" hidden>
      {topic_tabs}
    </div>
    <div class="folder">
{outlet_panels}

{topic_panels}
    </div>
  </div>
</main>

<script>
function openFolder(group, id) {{
  document.querySelectorAll('.panel').forEach(p =>
    p.hidden = !(p.dataset.group === group && p.dataset.id === id));
  document.querySelectorAll('.tab').forEach(t =>
    t.classList.toggle('active', t.dataset.group === group && t.dataset.id === id));
}}
function setView(v) {{
  document.getElementById('tabs-outlet').hidden = v !== 'outlet';
  document.getElementById('tabs-topic').hidden  = v !== 'topic';
  document.getElementById('btn-outlet').classList.toggle('active', v === 'outlet');
  document.getElementById('btn-topic').classList.toggle('active', v === 'topic');
  const first = document.querySelector('#tabs-' + v + ' .tab');
  openFolder(v, first.dataset.id);
}}
</script>

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
