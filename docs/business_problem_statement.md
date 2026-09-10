# Business Problem Statement

## Client context
A fictional retail bank, **Northstar Digital Bank**, onboards approximately 20,000 applicants per day across web, branch-assisted and mobile channels. Identity documents arrive as mobile photos, scans and PDF-derived images. The current KYC utility was built incrementally over several releases and is now a dependency in the onboarding flow.

## Current-state pain
- Manual reviewers inspect a large proportion of routine cases.
- Document extraction logic is tied to line prefixes, templates and regular expressions.
- OCR quality varies with blur, rotation, cropping and capture conditions.
- Harmless differences in names and formatting create review referrals.
- Expired or suspicious evidence must be handled consistently.
- Operations teams cannot easily explain why some cases were referred.
- Audit teams require traceable evidence of what the service extracted and why a decision occurred.
- Changes to document formats frequently require emergency parser changes.
- Business teams report inconsistent behavior between apparently similar cases.

## Current operational expectations
- Approximately 20,000 applications/day
- Typically 2–3 identity documents/application
- Peak load assumption: 15 verification requests/sec
- Synchronous pre-check expected to remain responsive under peak load
- Identity evidence must not be silently dropped
- Decisions must be reproducible from retained evidence
- Manual review referrals should contain enough context for an analyst to investigate
- Sensitive data handling must follow enterprise security and privacy controls

## Current constraints
- The training repository must run without external API keys or network access.
- Existing API paths are consumed by upstream systems and cannot be casually broken.
- Operations rely on current reason codes for case triage.
- Historical behavior is represented by the regression tests and expected baseline outputs.
- All data in this repository is synthetic and fabricated for training.
