name: Daily Data Update
# Runs entirely on GitHub's own servers -- no dependency on your computer
# being on, logged in, or even powered on.
#
# UPDATED: instead of one fixed-time run guessing when NSE has published,
# this polls every 5 minutes for NSE's daily bhavcopy file to actually
# be available, and runs the full pipeline the moment it shows up. The
# original 6:30pm run is kept as an UNCONDITIONAL fallback -- it always
# attempts the full pipeline regardless of the check (same behavior as
# before this change), so if NSE is ever later than the poll window, you
# still get today's update guaranteed. Weekends/holidays still fire and
# just get the same graceful "[miss] ... holiday" handling fetch_data.py
# already has -- harmless, a few wasted seconds those days.
#
# GitHub Actions cron is UTC:
#   */5 11-12 * * 1-5  -> every 5 min, 11:00-12:55 UTC = 4:30pm-6:25pm IST (poll)
#   0 13 * * 1-5        -> 13:00 UTC = 6:30pm IST (unconditional fallback, unchanged)
#
# Idempotency: every trigger (poll, fallback, or manual) first checks
# today's date against the most recent commit message on this branch. If
# today's update already went out (an earlier poll caught it), the run
# exits in a couple seconds without re-running classification/fetch/
# export/push -- this is what keeps 5-minute polling cheap. Only one poll
# per day actually ends up running the full pipeline.
#
# Honest caveat, straight from GitHub's own docs: scheduled workflows can
# be delayed during periods of high load across GitHub -- usually by a
# few minutes, occasionally longer, and 5-minute cron isn't always exact
# to the minute either. Still far better than a hardcoded guess.
on:
  schedule:
    - cron: "*/5 11-12 * * 1-5"   # poll: 4:30pm-6:25pm IST, every 5 min
    - cron: "0 13 * * 1-5"        # unconditional fallback: 6:30pm IST
  workflow_dispatch:
    inputs:
      force_reclassify:
        description: "Force full re-classification (tick this once a month, or after a known industry change -- otherwise leave unticked for the normal daily run)"
        required: false
        type: boolean
        default: false
permissions:
  contents: write   # needed to commit the regenerated data files back to the repo
jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Check whether to run today's update
        id: gate
        run: |
          TODAY=$(date -u +'%Y-%m-%d')
          LAST_MSG=$(git log -1 --pretty=%s 2>/dev/null || echo "")

          if echo "$LAST_MSG" | grep -q "$TODAY"; then
            echo "Already updated today (last commit: \"$LAST_MSG\") -- skipping."
            echo "proceed=false" >> "$GITHUB_OUTPUT"
            exit 0
          fi

          if [ "${{ github.event_name }}" = "workflow_dispatch" ] || [ "${{ github.event.schedule }}" = "0 13 * * 1-5" ]; then
            echo "Manual run or 6:30pm fallback -- proceeding regardless of NSE publish status."
            echo "proceed=true" >> "$GITHUB_OUTPUT"
            exit 0
          fi

          FNAME="sec_bhavdata_full_$(date -u +'%d%m%Y').csv"
          URL="https://archives.nseindia.com/products/content/${FNAME}"
          RESULT=$(curl -s -o /dev/null -w "%{http_code} %{size_download}" \
            -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36" \
            -H "Accept: text/csv,application/csv,*/*" \
            "$URL")
          HTTP_CODE=$(echo "$RESULT" | cut -d' ' -f1)
          BYTES=$(echo "$RESULT" | cut -d' ' -f2)
          echo "NSE check for $FNAME: status=$HTTP_CODE, bytes=$BYTES"

          if [ "$HTTP_CODE" = "200" ] && [ "$BYTES" -gt 0 ]; then
            echo "Bhavcopy is live -- proceeding."
            echo "proceed=true" >> "$GITHUB_OUTPUT"
          else
            echo "Not published yet -- will check again in 5 min (or fall back to 6:30pm)."
            echo "proceed=false" >> "$GITHUB_OUTPUT"
          fi

      - name: Set up Python
        if: steps.gate.outputs.proceed == 'true'
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      # sector_strength.db isn't committed to the repo (and shouldn't
      # be -- it's a growing binary file that changes every run). Instead
      # it's cached between runs: restore whatever the last run saved,
      # then save a fresh copy at the end of this one. restore-keys uses
      # a prefix match, so it always picks up the most recent cache
      # regardless of which exact run produced it.
      - name: Restore database from cache
        if: steps.gate.outputs.proceed == 'true'
        uses: actions/cache/restore@v4
        with:
          path: sector_strength.db
          key: sector-strength-db-${{ github.run_id }}
          restore-keys: |
            sector-strength-db-

      - name: Install dependencies
        if: steps.gate.outputs.proceed == 'true'
        run: pip install pandas requests beautifulsoup4

      - name: Classify basic industries
        if: steps.gate.outputs.proceed == 'true'
        run: |
          if [ "${{ github.event.inputs.force_reclassify }}" = "true" ]; then
            echo "Force reclassify requested -- re-walking all industries (this run will take longer than usual)"
            python classify_via_screener.py --force
          else
            python classify_via_screener.py
          fi

      - name: Fetch data
        if: steps.gate.outputs.proceed == 'true'
        run: python fetch_data.py

      - name: Export snapshot
        if: steps.gate.outputs.proceed == 'true'
        run: python export_snapshot.py

      - name: Save database to cache
        if: steps.gate.outputs.proceed == 'true'
        uses: actions/cache/save@v4
        with:
          path: sector_strength.db
          key: sector-strength-db-${{ github.run_id }}

      - name: Commit and push updated data
        if: steps.gate.outputs.proceed == 'true'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/data/
          git diff --staged --quiet || git commit -m "Automated daily update $(date -u +'%Y-%m-%d')"
          git push

      - name: Notify via Telegram
        if: steps.gate.outputs.proceed == 'true' && success()
        run: |
          curl -s -X POST "https://api.telegram.org/bot${{ secrets.TG_BOT_TOKEN }}/sendMessage" \
            -d chat_id=${{ secrets.TG_CHAT_ID }} \
            -d text="Sector strength site updated"

      - name: Notify via Telegram on failure
        if: steps.gate.outputs.proceed == 'true' && failure()
        run: |
          curl -s -X POST "https://api.telegram.org/bot${{ secrets.TG_BOT_TOKEN }}/sendMessage" \
            -d chat_id=${{ secrets.TG_CHAT_ID }} \
            -d text="⚠️ Sector strength update FAILED — check GitHub Actions logs"
