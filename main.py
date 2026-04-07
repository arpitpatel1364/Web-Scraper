import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import io
import time
import zipfile
from urllib.parse import urljoin, urlparse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Business Fair Deep Scraper",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        text-align: center;
        color: white;
    }
    .main-header h1 { font-size: 2.4rem; font-weight: 800; margin: 0; color: #e94560; }
    .main-header p  { font-size: 1rem; color: #a8b2d8; margin-top: 0.5rem; }

    .stat-card {
        background: linear-gradient(135deg, #0f3460, #16213e);
        border: 1px solid #e94560;
        border-radius: 10px;
        padding: 1rem 1.5rem;
        text-align: center;
        color: white;
    }
    .stat-card h2 { font-size: 2rem; color: #e94560; margin: 0; }
    .stat-card p  { color: #a8b2d8; margin: 0; font-size: 0.85rem; }

    .log-box {
        background: #0a0a0a;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 1rem;
        font-family: 'Courier New', monospace;
        font-size: 0.78rem;
        color: #00ff88;
        max-height: 260px;
        overflow-y: auto;
    }

    .stButton > button {
        background: linear-gradient(135deg, #e94560, #c23152);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.6rem 1.4rem;
        font-weight: 700;
        width: 100%;
        font-size: 1rem;
    }
    .stButton > button:hover { opacity: 0.88; }
    .stDownloadButton > button {
        background: linear-gradient(135deg, #0f3460, #1a5276);
        color: white !important;
        border: none;
        border-radius: 8px;
        padding: 0.55rem 1.2rem;
        font-weight: 600;
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
  <h1>🏢 Business Fair Deep Scraper</h1>
  <p>Intelligent multi-page scraper · Extracts emails, websites & business details with pagination support</p>
</div>
""", unsafe_allow_html=True)

# ── Sidebar Config ────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Scraper Settings")
    delay      = st.slider("Request delay (sec)", 0.5, 5.0, 1.5, 0.5,
                           help="Polite crawl delay between pages")
    max_pages  = st.slider("Max pages to scrape", 1, 100, 20)
    timeout    = st.slider("Request timeout (sec)", 5, 60, 20)
    deep_scrape = st.toggle("Deep scrape (follow profile links)", value=True)
    max_detail = st.slider("Max detail pages per listing", 1, 50, 10,
                           disabled=not deep_scrape)
    st.divider()
    st.markdown("### 📋 Export Options")
    incl_raw   = st.checkbox("Include raw context column", value=False)
    st.markdown("---")
    st.info("💡 Tip: Enable deep scraping to follow 'View Profile' links and grab hidden emails.")

# ── Helpers ───────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

EMAIL_RE  = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
PHONE_RE  = re.compile(r'(?:\+?\d[\d\s\-().]{7,15}\d)')

def safe_get(url, timeout_s=20, logs=None):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout_s)
        r.raise_for_status()
        return r
    except Exception as e:
        if logs is not None:
            logs.append(f"⚠️  {url} → {e}")
        return None

def extract_emails(text):
    return list(set(EMAIL_RE.findall(text)))

def extract_phones(text):
    raw = PHONE_RE.findall(text)
    return list(set(p.strip() for p in raw if len(re.sub(r'\D', '', p)) >= 7))

def find_pagination_urls(soup, base_url):
    """Detect next-page links across common pagination patterns."""
    next_urls = []
    # Pattern 1: rel="next"
    for tag in soup.find_all('a', rel=lambda r: r and 'next' in r):
        href = tag.get('href', '')
        if href:
            next_urls.append(urljoin(base_url, href))
    # Pattern 2: common text indicators
    if not next_urls:
        for tag in soup.find_all('a'):
            txt = tag.get_text(strip=True).lower()
            if txt in ('next', 'next »', 'next page', '›', '»', 'next →', '>'):
                href = tag.get('href', '')
                if href and '#' not in href:
                    next_urls.append(urljoin(base_url, href))
    # Pattern 3: ?page=N or ?p=N increments
    if not next_urls:
        for tag in soup.find_all('a', href=True):
            href = tag['href']
            if re.search(r'[?&](page|p|pg|offset|start)=\d+', href, re.I):
                next_urls.append(urljoin(base_url, href))
    return list(dict.fromkeys(next_urls))  # deduplicate preserving order

def parse_entries(soup, base_url):
    """Extract business entries from a page."""
    results = []
    seen = set()

    containers = soup.find_all(['article', 'div', 'li', 'tr', 'section'])
    for item in containers:
        text = item.get_text(separator=' ').strip()
        emails  = extract_emails(text)
        phones  = extract_phones(text)

        # External links
        links   = item.find_all('a', href=True)
        website = ''
        detail_links = []
        for lnk in links:
            href = lnk['href']
            full = urljoin(base_url, href)
            parsed = urlparse(full)
            if parsed.scheme in ('http', 'https'):
                if urlparse(base_url).netloc not in parsed.netloc:
                    if not website:
                        website = full
                else:
                    if any(k in href.lower() for k in ('exhibitor','profile','company','participant','booth','vendor','member','listing')):
                        detail_links.append(full)

        company_name = ''
        for tag in ['h1','h2','h3','h4','strong','b']:
            el = item.find(tag)
            if el:
                company_name = el.get_text(strip=True)[:120]
                break

        context = text[:150].replace('\n', ' ')

        if emails or website or phones:
            key = (tuple(sorted(emails)), website, company_name)
            if key not in seen:
                seen.add(key)
                results.append({
                    'company':      company_name,
                    'emails':       emails,
                    'phones':       phones,
                    'website':      website,
                    'detail_links': list(dict.fromkeys(detail_links)),
                    'context':      context,
                })
    return results

def deep_scrape_entry(entry, base_url, timeout_s, logs, max_d):
    """Follow profile/detail links to gather more contact info."""
    for url in entry['detail_links'][:max_d]:
        if logs is not None:
            logs.append(f"  🔍 Detail: {url}")
        r = safe_get(url, timeout_s, logs)
        if not r:
            continue
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(separator=' ')
        entry['emails']  = list(set(entry['emails']  + extract_emails(text)))
        entry['phones']  = list(set(entry['phones']  + extract_phones(text)))
        if not entry['website']:
            for lnk in soup.find_all('a', href=True):
                h = lnk['href']
                f = urljoin(url, h)
                if urlparse(f).netloc and urlparse(base_url).netloc not in urlparse(f).netloc:
                    entry['website'] = f
                    break
        if not entry['company']:
            for tag in ['h1','h2','h3']:
                el = soup.find(tag)
                if el:
                    entry['company'] = el.get_text(strip=True)[:120]
                    break
    return entry

def build_excel(df):
    wb = Workbook()
    ws = wb.active
    ws.title = "Exhibitors"

    # ── Summary sheet ──
    ws2 = wb.create_sheet("Summary")
    ws2['A1'] = "Business Fair Scrape — Summary"
    ws2['A1'].font = Font(bold=True, size=14, color="FFFFFF")
    ws2['A1'].fill = PatternFill("solid", start_color="0F3460")
    ws2.merge_cells('A1:C1')
    stats = [
        ("Total Companies",       len(df)),
        ("With Email",            int(df['Email'].astype(bool).sum())),
        ("With Website",          int(df['Website'].astype(bool).sum())),
        ("With Phone",            int(df['Phone'].astype(bool).sum())),
        ("Complete (email+web)",  int(((df['Email'].astype(bool)) & (df['Website'].astype(bool))).sum())),
    ]
    for i,(k,v) in enumerate(stats, start=3):
        ws2[f'A{i}'] = k
        ws2[f'B{i}'] = v
        ws2[f'A{i}'].font = Font(bold=True)
    ws2.column_dimensions['A'].width = 28
    ws2.column_dimensions['B'].width = 14

    # ── Main sheet ──
    cols = [c for c in df.columns]
    header_fill = PatternFill("solid", start_color="E94560")
    header_font = Font(bold=True, color="FFFFFF", size=10)
    thin = Side(style='thin', color='DDDDDD')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for ci, col in enumerate(cols, 1):
        cell = ws.cell(row=1, column=ci, value=col)
        cell.fill   = header_fill
        cell.font   = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = border

    row_fill_a = PatternFill("solid", start_color="F8F9FA")
    row_fill_b = PatternFill("solid", start_color="FFFFFF")

    for ri, row in enumerate(df.itertuples(index=False), start=2):
        fill = row_fill_a if ri % 2 == 0 else row_fill_b
        for ci, val in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci, value=str(val) if val else '')
            cell.alignment = Alignment(wrap_text=True, vertical='top')
            cell.fill = fill
            cell.border = border
            # Hyperlink for websites
            if cols[ci-1] == 'Website' and val and str(val).startswith('http'):
                cell.hyperlink = str(val)
                cell.font = Font(color='0563C1', underline='single')
            # Hyperlink for emails
            if cols[ci-1] == 'Email' and val and '@' in str(val):
                first_email = str(val).split(',')[0].strip()
                cell.hyperlink = f"mailto:{first_email}"
                cell.font = Font(color='0563C1', underline='single')

    # Column widths
    width_map = {'#': 5, 'Company Name': 30, 'Email': 36, 'Website': 36,
                 'Phone': 18, 'Source Page': 28, 'Context': 40}
    for ci, col in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(ci)].width = width_map.get(col, 20)

    ws.row_dimensions[1].height = 28
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()

def build_zip(df, excel_bytes):
    readme = """# Business Fair Deep Scraper

## What is this?
A multi-page web scraper that extracts business details (names, emails,
websites, phone numbers) from business fair / trade show exhibitor directories.

## Features
- Automatic pagination detection (next-page links, ?page=N, etc.)
- Deep scraping: follows individual exhibitor profile links
- Extracts emails, phone numbers, websites & company names
- Exports to a beautifully formatted Excel file
- Exports to ZIP with this README and setup instructions

## Output — Excel columns
| Column      | Description                            |
|-------------|----------------------------------------|
| #           | Row index                              |
| Company Name| Business / exhibitor name              |
| Email       | Contact email(s) found                 |
| Phone       | Phone number(s) found                  |
| Website     | Company website URL                    |
| Source Page | Which fair directory page it came from |
| Context     | Short snippet of surrounding text      |

## Notes
- Some sites load data via JavaScript → those emails won't appear
- Respect robots.txt and the site's terms of service
- Use a reasonable crawl delay (1-2 sec) to avoid overloading servers
"""

    setup = """# Setup Guide

## Requirements
- Python 3.9+
- pip

## Installation
```bash
# 1. Clone / copy the project
cd business-fair-scraper

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\\Scripts\\activate

# 3. Install dependencies
pip install streamlit requests beautifulsoup4 pandas openpyxl lxml
```

## Running
```bash
streamlit run main.py
```
Then open http://localhost:8501 in your browser.

## Usage
1. Paste the exhibitor directory URL (e.g. https://fair.com/exhibitors)
2. Adjust settings in the left sidebar (delay, max pages, deep scrape)
3. Click **Start Scraping**
4. Download the Excel file or full ZIP when done

## Troubleshooting
| Problem                        | Solution                                      |
|-------------------------------|-----------------------------------------------|
| No emails found               | Enable deep scrape to follow profile links    |
| Blocked (403 / 429)           | Increase crawl delay to 3-5 sec              |
| Pagination not detected       | Paste direct page URL (page=1)               |
| Data loads via JavaScript     | Site uses React/Vue — scraper can't reach it  |

## Dependencies
```
streamlit>=1.32
requests>=2.31
beautifulsoup4>=4.12
pandas>=2.1
openpyxl>=3.1
lxml>=4.9
```
"""

    stats_txt = f"""Scrape Statistics
=================
Total companies : {len(df)}
With email      : {int(df['Email'].astype(bool).sum())}
With website    : {int(df['Website'].astype(bool).sum())}
With phone      : {int(df['Phone'].astype(bool).sum())}
Complete entries: {int(((df['Email'].astype(bool)) & (df['Website'].astype(bool))).sum())}
"""

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md",        readme)
        zf.writestr("SETUP.md",         setup)
        zf.writestr("scrape_stats.txt", stats_txt)
        zf.writestr("main.py",          open(__file__).read())
        zf.writestr("fair_participants.xlsx", excel_bytes)
    zbuf.seek(0)
    return zbuf.read()

# ── Main UI ───────────────────────────────────────────────────────────────────
url_input = st.text_input(
    "🌐 Fair Directory URL:",
    placeholder="https://fair-website.com/exhibitors",
    help="Paste the exhibitor / participant directory page URL"
)

col_btn1, col_btn2 = st.columns([1, 3])
with col_btn1:
    start = st.button("🚀 Start Scraping")

if start:
    if not url_input.strip():
        st.warning("⚠️ Please enter a URL first.")
    else:
        base_url = url_input.strip()
        logs     = []
        all_entries = []
        pages_scraped = 0
        visited_pages = set()
        current_url   = base_url

        st.markdown("---")
        st.markdown("### 📡 Live Scraping Log")
        log_placeholder   = st.empty()
        progress_bar      = st.progress(0, text="Starting…")
        status_placeholder = st.empty()

        def refresh_log():
            log_placeholder.markdown(
                "<div class='log-box'>" +
                "<br>".join(logs[-30:]) +
                "</div>",
                unsafe_allow_html=True
            )

        # ── Pagination loop ───────────────────────────────────────────────────
        while current_url and pages_scraped < max_pages and current_url not in visited_pages:
            visited_pages.add(current_url)
            logs.append(f"📄 Page {pages_scraped+1}: {current_url}")
            refresh_log()
            progress_bar.progress(
                min(pages_scraped / max_pages, 0.95),
                text=f"Scraping page {pages_scraped+1} of up to {max_pages}…"
            )

            r = safe_get(current_url, timeout, logs)
            if not r:
                logs.append("❌ Could not load page — stopping pagination.")
                refresh_log()
                break

            soup = BeautifulSoup(r.text, 'html.parser')
            entries = parse_entries(soup, current_url)
            logs.append(f"   → Found {len(entries)} entries on this page")
            refresh_log()

            # Deep scrape
            if deep_scrape:
                for ei, entry in enumerate(entries):
                    if entry['detail_links']:
                        logs.append(f"   🕵️ Deep scraping entry {ei+1}/{len(entries)}: {entry['company'] or '(unknown)'}")
                        refresh_log()
                        entries[ei] = deep_scrape_entry(entry, current_url, timeout, logs, max_detail)
                        time.sleep(delay * 0.5)

            for e in entries:
                e['source_page'] = current_url
            all_entries.extend(entries)

            # Find next page
            next_candidates = find_pagination_urls(soup, current_url)
            next_url = None
            for nc in next_candidates:
                if nc not in visited_pages:
                    next_url = nc
                    break
            current_url = next_url
            pages_scraped += 1

            if current_url:
                time.sleep(delay)

        progress_bar.progress(1.0, text="✅ Scraping complete!")
        logs.append(f"🏁 Done! {len(all_entries)} raw entries from {pages_scraped} page(s).")
        refresh_log()

        # ── Build DataFrame ───────────────────────────────────────────────────
        if all_entries:
            rows = []
            for i, e in enumerate(all_entries, 1):
                row = {
                    '#':           i,
                    'Company Name': e.get('company', ''),
                    'Email':       ', '.join(e.get('emails', [])),
                    'Phone':       ', '.join(e.get('phones', [])),
                    'Website':     e.get('website', ''),
                    'Source Page': e.get('source_page', ''),
                }
                if incl_raw:
                    row['Context'] = e.get('context', '')
                rows.append(row)

            df = pd.DataFrame(rows)
            # De-dupe on company+email combo
            df.drop_duplicates(subset=['Company Name', 'Email'], keep='first', inplace=True)
            df.reset_index(drop=True, inplace=True)
            df['#'] = df.index + 1

            # ── Stats row ────────────────────────────────────────────────────
            st.markdown("### 📊 Results Summary")
            c1, c2, c3, c4, c5 = st.columns(5)
            for col_obj, label, val in [
                (c1, "Companies",    len(df)),
                (c2, "With Email",   int(df['Email'].astype(bool).sum())),
                (c3, "With Website", int(df['Website'].astype(bool).sum())),
                (c4, "With Phone",   int(df['Phone'].astype(bool).sum())),
                (c5, "Pages Crawled", pages_scraped),
            ]:
                col_obj.markdown(
                    f"<div class='stat-card'><h2>{val}</h2><p>{label}</p></div>",
                    unsafe_allow_html=True
                )

            st.markdown("### 📋 Extracted Data")
            st.dataframe(df, use_container_width=True, height=420)

            # ── Exports ───────────────────────────────────────────────────────
            st.markdown("### 💾 Download")
            excel_bytes = build_excel(df)
            zip_bytes   = build_zip(df, excel_bytes)

            dl1, dl2 = st.columns(2)
            with dl1:
                st.download_button(
                    label="📥 Download Excel (.xlsx)",
                    data=excel_bytes,
                    file_name="fair_participants.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            with dl2:
                st.download_button(
                    label="📦 Download Full ZIP (Excel + README + SETUP + Code)",
                    data=zip_bytes,
                    file_name="business_fair_scraper_export.zip",
                    mime="application/zip",
                )
        else:
            st.info(
                "ℹ️ No business details found. Possible reasons:\n"
                "- Page uses JavaScript to load data (React/Vue/Angular)\n"
                "- Emails hidden behind login walls\n"
                "- Try enabling **Deep Scrape** mode\n"
                "- Try a different starting URL (e.g. ?page=1)"
            )

st.divider()
st.caption(
    "🛡️ Use responsibly · Respect robots.txt & site ToS · "
    "Increase crawl delay to avoid overloading servers"
)