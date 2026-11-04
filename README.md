# football-live

Publishes ESPN football snapshots through the existing live scheduler and the
six-hour schedule workflow. Clients continue to read the same JSON URLs.

The schedule seeds missing match IDs; it never replaces an existing live row.
Fresh ESPN responses update live rows, but a finished match cannot become
nonterminal again. Final score corrections are still accepted.

Monitoring starts 30 minutes before kickoff and continues until a terminal
status is received. There is no four-hour cutoff: missed updates are recovered
automatically while the kickoff belongs to today or yesterday in Europe/Rome.
Older rows expire at rollover. No result is inferred from elapsed wall time.
Live runs bootstrap a missing schedule, and schedule runs also publish live files.
External scheduler availability and ESPN responses still determine freshness.
