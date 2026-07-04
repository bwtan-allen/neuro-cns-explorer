name: Refresh neuroscience publication data

on:
  schedule:
    # 08:00 UTC on the 1st of every month
    - cron: "0 8 1 * *"
  workflow_dispatch: {}          # allow manual "Run workflow" from the Actions tab

permissions:
  contents: write                # allow the job to commit refreshed data back

concurrency:
  group: refresh-data
  cancel-in-progress: false

jobs:
  refresh:
    runs-on: ubuntu-latest
    timeout-minutes: 330         # generous; incremental runs are much shorter
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Refresh data
        env:
          # Optional but strongly recommended: raises PubMed limit 3->10 req/s.
          # Add it under Settings > Secrets and variables > Actions > New repository secret.
          NCBI_API_KEY: ${{ secrets.NCBI_API_KEY }}
        run: python refresh_data.py

      - name: Commit refreshed data
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add neuro_stats.json data/ exports/ 2>/dev/null || true
          if git diff --cached --quiet; then
            echo "No data changes to commit."
          else
            git commit -m "chore: monthly data refresh ($(date -u +%Y-%m-%d))"
            git push
          fi
