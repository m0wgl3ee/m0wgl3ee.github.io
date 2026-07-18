# napatkongsawad.com — portfolio

Static portfolio site, generated from `clips.json` by `build.py`.

## Adding a new clip

1. Edit `clips.json`, append an entry to `"clips"`:

   ```json
   {
     "section": "nhk",                      // nhk | ap | bloomberg | freelance
     "pub": "NHK World",                    // label shown on the card
     "date": "2026-07-18",                  // ISO date (or "date_label": "Backstories")
     "title": "Headline exactly as published",
     "url": "https://youtu.be/XXXXXXXXXXX", // article or video URL
     "topic": "scams",                      // or "topics": ["breaking","scams"]
     "summary": "1-2 sentences shown on hover"
   }
   ```

   Topic ids are defined in the "topics" list in clips.json.

   For a PDF clipping: drop the file into `clips/` and use
   `"file": "clips/my-story.pdf"` instead of `"url"`.

2. Run the build:

   ```
   python build.py
   ```

   Thumbnails are fetched automatically — YouTube thumbnail for videos,
   the article's og:image for links, a page-1 snapshot for PDFs (needs
   `pip install pymupdf`) — saved into `img/`, and cached in `clips.json`.

3. Commit and push — GitHub Pages redeploys automatically.

## Notes

- If a site blocks scraping (Bloomberg does), the card falls back to a styled
  publication-monogram tile. To use a hand-picked image, save it to `img/`
  and set `"thumb": "img/name.jpg"` on the entry. Set `"no_thumb": true` to
  stop the build from re-trying the fetch every run.
- `index.html` is generated — don't edit it by hand; change `build.py`
  (layout/CSS lives in its `TEMPLATE` string) or `clips.json` instead.
- New sections: add to `"sections"` in `clips.json`; nav updates automatically.
