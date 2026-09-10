# Engineering Challenge Register

This register captures unresolved questions raised during handover. It deliberately avoids prescribing an implementation approach.

## Document handling
1. How reliably does the service behave when document orientation, noise, spacing or line order changes?
2. Which parser assumptions are coupled to the current synthetic document format?
3. Which fields can be silently omitted without causing a hard failure?
4. How are unsupported or unknown document layouts handled?

## Identity consistency
5. How does the service determine whether multiple documents belong to the same person?
6. What happens when names differ because of initials, punctuation, spacing, OCR corruption or transliteration?
7. Does a matching date of birth compensate for a name mismatch, and should it?
8. Can inconsistent evidence be incorrectly aggregated into a case-level decision?

## Risk and decisioning
9. Which decisions are policy decisions and which are side effects of parser behavior?
10. Are reason codes sufficient for an analyst to reconstruct the decision?
11. Is the completeness score meaningful as a confidence measure?
12. Can suspicious evidence be missed when required fields are still present?

## Operations
13. Can the service explain failures across a multi-document case using one correlation trail?
14. How are retries, duplicates and repeated requests handled?
15. What evidence exists for performance, throughput and failure-rate assumptions?
16. Which operational failures would currently require source-code inspection?

## Security and privacy
17. Which endpoints are callable without identity or authorization controls?
18. Where is sensitive synthetic identity data written or logged?
19. What retention, deletion and minimization controls are absent?
20. Which inputs could cause unsafe file access, malformed parsing or unexpected resource consumption?
