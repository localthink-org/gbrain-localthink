# Daily backup via cron

Two integration paths — pick one.

## A. Hermes Agent cron (if you run Hermes)

Create a `no_agent` job so the script runs without LLM cost:

```sh
# inside Hermes
cronjob action=create \
  name="GBrain+LTF daily backup" \
  schedule="every day at 18:00" \
  script="backup.sh" \
  no_agent=true \
  deliver="local"
```

`no_agent` runs `scripts/backup.sh` on schedule and delivers its stdout verbatim (or nothing when there's no change).

## B. Plain system cron

Edit your crontab (`crontab -e`) and add:

```cron
# daily 18:00 — adjust paths to your setup
0 18 * * * cd $HOME/path/to/gbrain-localthink && ./scripts/backup.sh >> $HOME/.hermes/scripts/backup.log 2>&1
```

Make sure `$HOME/.profile` (or equivalent) has `gbrain` and any needed tool on PATH; the script also self-sources `~/.profile`.

## Notes

- The script is **idempotent**: no-change runs skip the push entirely.
- Empty sessions and sessions the converter blocks are counted in the converter summary. A blocked session deletes its previous `.ltf.md` and hash so a stale copy is not committed. That does not abort the converter.
- The repo-wide secret scan is different: a hit exits `backup.sh` with code 2 and does not push.
- `git push` failures are printed to stderr and exit non-zero. The script retries once after `git pull --rebase`. Redirect stderr into the cron log (`2>&1`) or a failed push is only visible if you capture it.
- Logs go to stdout and stderr (or your log file); check them via the cron deliver target or the log path.
