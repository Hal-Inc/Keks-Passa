name: Automated Daily Lisbon Events Refresh

on:
  schedule:
    # Triggers every morning at 04:00 AM UTC
    - cron: '0 4 * * *'
  workflow_dispatch: # Allows manual trigger from GitHub anytime

jobs:
  scrape-and-publish:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4

      - name: Run Event Scraper Script
        run: python scraper.py

      - name: Commit and Push Updated events.json
        run: |
          git config --global user.name "Lisbon Event Bot"
          git config --global user.email "bot@lisbonevents.local"
          git add events.json
          git status
          git commit -m "chore: auto-update daily events dataset [$(date +'%Y-%m-%d')]" || exit 0
          git push
```