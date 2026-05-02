# intraday_log/

One markdown file per hourly signal scan, named `YYYY-MM-DDTHH.md` (UTC).

The hourly routine writes to this directory. Each entry should contain:

- timestamp (UTC, hour granularity);
- a STRONG / WATCH / AVOID classification for each of the 10 universe symbols;
- the panel of return windows that drove each classification (r1d, r5d, r60d, vol);
- if any symbol crossed a regime threshold since the previous run (e.g. went
  from WATCH to STRONG), call it out at the top.

Rotated old entries off after ~30 days to keep the directory readable. The
routine itself can prune.
