"""Google Sheet two-way sync (Step 13).

- `design`  the approved look: stages, colours, cell builders, formulas and their Python twin
- `client`  Google API access and the views this environment writes (live sheets, or staging in dev)
- `state`   sync bookkeeping: the sheet_state marker, snapshots and the lock
- `push`    database to sheet (build everything, validate, one atomic write per view, then snapshot)
- `pull`    sheet to database (edits against each sheet's own snapshot, conflict rules, activities)
- `sync`    pull, then push: what the schedule runs
- `render`  PDF export of every tab for visual checks
"""
