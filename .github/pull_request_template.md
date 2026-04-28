## Summary

- Describe the change clearly and concretely.

## Testing

- [ ] `pytest -q`
- [ ] `ruff check hindsight tests`
- [ ] Manual smoke test if relevant

## Docs

- [ ] README updated if CLI behavior changed
- [ ] `docs/` updated if extension points or config changed
- [ ] `.env.example` updated if a new env var was added

## Privacy / Security

- [ ] No secrets, transcripts, `.env`, or SQLite data files are included
- [ ] New network behavior is documented
- [ ] New source timestamps are normalized to UTC
