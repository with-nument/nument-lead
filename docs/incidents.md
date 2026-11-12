# Incidents

What to do in the first 15 minutes when something goes wrong, and a log of what happened (Step 18.8). Keep
entries short and factual. Never paste a secret, a full phone number or a full email into this file.

## Playbook

| Incident | Contain (first 15 minutes) | Fix | Record |
|---|---|---|---|
| A key or secret leaked | Revoke or rotate it at the provider; update the GitHub and Render secrets | Find how it leaked; add a gitleaks rule if a pattern was missed | This log |
| Personal data exposed (for example a public link to data) | Remove access; switch off the affected feature | Assess who is affected. Under India's DPDP Rules a personal data breach is reported to the Data Protection Board and to the people affected (check the current timeline) | This log |
| A website owner or platform complains | Switch the source off on the Engine page | Reply politely within 48 hours; delete their data if asked ([data-policy.md](data-policy.md#deletion-requests)) | This log; add them to `engine/config/exclusions.yaml` |
| WhatsApp restricts the sending number | Stop new chats for 48 hours | Lower the daily volume; review message similarity and complaints | Weekly report |
| The wrong person is contacted again | Add the number to suppression | Find why that phone was attached to the business; fix verification | Add the business to the golden set as a bad example |
| Spend spike | The budget guard stops optional work; if needed, disable the workflows | Find the task that overspent in `costs`; fix its limits | Weekly report |
| The pipeline writes bad leads or breaks the sheets | Disable the workflows (GitHub, Actions, each workflow, Disable) | Restore the sheets from version history; fix on dev; re-run the dry-run nights | This log |

## Log

Newest first. One entry per incident.

```
### YYYY-MM-DD: short title
- What happened:
- Impact (who or what was affected, for how long):
- Contained by (what, when):
- Root cause:
- Fix and follow-up (with links to commits or pull requests):
- Status: open | closed
```

### Open actions

- Rotate the Google service-account key and revoke the GitHub personal access token that were shared in a
  chat during setup (Step 18.7.5). Close this item with the date once both are done.
