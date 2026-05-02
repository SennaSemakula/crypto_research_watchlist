# research_log/

One markdown file per daily calibration run, named `YYYY-MM-DD.md`.

The 03:00 UTC calibration routine writes to this directory. The format is
loose, but each entry should at minimum include:

- the date and which day-of-week schedule fired (Mon/Tue/.../Sun);
- the threshold sweep / regime / correlation table that was the focus;
- one or two sentences of interpretation;
- if any production knob in `config.yml` was changed, a "Calibration delta"
  section noting old -> new and the evidence justifying it.

Sunday entries are coherence reviews: they read the previous six days and
either confirm or revert any week's calibration drift.
