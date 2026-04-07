# Business Fair Deep Scraper

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

