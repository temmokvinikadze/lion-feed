# Lion Auctions → Meta Vehicles Catalog Feed

Auto-generated hourly XML feed of lionauctions.com vehicle listings, formatted for Meta (Facebook) Commerce Manager's Automotive Inventory Ads.

**Public feed URL** (after setup): `https://<your-username>.github.io/<repo-name>/feed.xml`

---

## What this does

1. GitHub Actions runs every hour on the hour (UTC).
2. `generate_feed.py` fetches all listing URLs from `lionauctions.com/listings-sitemap.xml` + `listings-sitemap2.xml`.
3. It scrapes each listing page (8 concurrent, ~2 min for ~1,700 cars).
4. It extracts make, model, year, VIN, mileage, price, fuel, transmission, drivetrain, condition, colors, and up to 20 images.
5. It writes `public/feed.xml` in Meta's Automotive Inventory Ads XML format.
6. GitHub Pages serves that file at a public URL.
7. Meta Commerce Manager reads the URL on its own schedule.

You do nothing after setup. When a new car is listed on the site, it appears in Meta within ~1 hour.

---

## One-time setup

### 1. Create a GitHub repo

- Go to https://github.com/new
- Repository name: e.g. `lion-feed`
- Public (required for free GitHub Pages)
- **Do NOT initialize** with README/gitignore/license (this repo already has them)

### 2. Push this code

From the folder you unzipped:

```bash
git init
git add .
git commit -m "Initial commit: Meta Vehicles feed generator"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

### 3. Enable GitHub Pages

- Go to your repo → **Settings** → **Pages**
- Under **Source**, select **GitHub Actions** (not "Deploy from a branch")
- Save

### 4. Run the workflow once manually

- Go to your repo → **Actions** tab
- Click **Generate Meta Vehicles Feed** in the left sidebar
- Click **Run workflow** → **Run workflow** (green button)
- Wait ~2–3 minutes for it to complete

### 5. Verify the feed

Open in the browser:
```
https://<your-username>.github.io/<repo-name>/feed.xml
```

You should see the full XML with all active listings.

### 6. Connect to Meta

- Go to Business Manager → **Commerce Manager** → **Catalogs** → **Add Catalog**
- Choose **Vehicles** (NOT "Ecommerce")
- Choose **Upload product info** → **Scheduled feed** (or "Data feed")
- Paste the URL: `https://<your-username>.github.io/<repo-name>/feed.xml`
- Frequency: **Hourly**
- Save

That's it. Meta will begin pulling the feed and your Vehicle catalog will populate within an hour.

---

## What runs and when

- The GitHub Actions workflow (`.github/workflows/generate-feed.yml`) fires:
  - On the hour, every hour (UTC)
  - Manually from the Actions tab (Run workflow button)
  - On push to `main` when `generate_feed.py` changes

- Free-tier GitHub Actions: 2,000 min/month included. Each run takes ~2–3 min, so 24 runs/day = ~90 min/day = well under the limit.

---

## Local test run

If you want to test locally before pushing:

```bash
pip install -r requirements.txt
python generate_feed.py
```

The output is written to `public/feed.xml`.

---

## Tweaking

Common changes in `generate_feed.py`:

- **`CONCURRENCY`** (line ~19): number of parallel HTTP requests. Currently `8`. Higher = faster but more load on the source site.
- **Sold listings**: currently filtered out (line ~208 `active = ...`). Remove that filter to include them as `availability: out of stock`.
- **Enum maps** (`FUEL`, `TRANS`, `DRIVE`, `COND`, `BODY`, `COLOR`): add Georgian→English mappings as needed.
- **Price choice**: currently uses `buy_now_usd` first, then `starting_bid_usd`. See `build_item()`.

---

## Troubleshooting

- **Workflow fails on first run**: often just a permission issue. Go to **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions**, save, and re-run.
- **Pages URL 404**: after enabling Pages, the first successful workflow run publishes the site. Give it a minute after the run finishes.
- **Meta says "invalid feed"**: open the URL and validate the XML with an XML linter. Common issues: BOM char, unclosed tags, invalid enum value in `fuel_type` / `body_style`.
- **Empty feed**: the site's HTML structure may have changed. Update the CSS selectors in `parse_listing()`.

---

## Notes

- The scraper touches only public pages. No WordPress login, no plugin, no changes to lionauctions.com.
- Rate limit is conservative (8 concurrent). If you see 429s, drop `CONCURRENCY` to 4.
- User-agent identifies the bot honestly.
