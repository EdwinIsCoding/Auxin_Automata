## Summary

<!-- What does this PR do? One to three bullet points. -->

- 

## Phase / Track

<!-- Which phase and track does this belong to? e.g. Phase 1A, Phase 2C, hotfix -->

## Test Plan

<!-- How did you verify this works? -->

- [ ] Unit tests pass (`make test`)
- [ ] Linting clean (`make lint`)
- [ ] Manual verification: <!-- describe -->

## Checklist

- [ ] No secrets or keypairs committed
- [ ] `.env.example` updated if new env vars added
- [ ] Agnosticism contract preserved — no `if AUXIN_SOURCE ==` branches in bridge or downstream
- [ ] Compliance events remain un-rate-limited and un-droppable
- [ ] Watchdog node still has zero imports of `auxin-sdk` and zero network calls

## Notes for Reviewer

<!-- Anything the reviewer should know: assumptions, open questions, follow-ups -->
