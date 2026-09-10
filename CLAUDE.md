You are working on the attached AI FDE Brownfield KYC repository.
Treat this as an inherited production system, not a greenfield rewrite.
GLOBAL ENGINEERING RULES
1. Inspect the repository and relevant tests before modifying code.
2. Do not blindly rewrite the application.
3. Preserve existing /v1 API compatibility unless a requirement explicitly requires an additive
change.
4. Preserve existing valid business behaviour unless a test or documented requirement
demonstrates that the behaviour is deficient.
5. Existing tests are regression evidence, not proof that the design is correct.
6. Use the synthetic repository data only. Do not introduce real PII.
7. The repository must remain runnable offline without external API keys.
8. External OCR, VLM, identity, fraud, registry or model services must be behind interfaces/
adapters and must have deterministic offline implementations.
9. Do not silently discard evidence.
10. Consequential identity decisions must not depend solely on an LLM.
11. Prefer deterministic code for computable validation and policy.
1
12. AI/model components may interpret ambiguous evidence but their outputs must be schema
validated.
13. Every important decision must be explainable from retained evidence.
14. Add tests before or alongside every material behavioural change.
15. Keep implementation modular and avoid unnecessary dependencies.
16. Do not expose sensitive identity attributes in unrestricted logs.
17. Never weaken security simply to make a test pass.
18. Do not fabricate successful verification of capabilities that are not actually implemented.
19. Update documentation when interfaces or behaviour change.
20. Run the complete existing and new test suite after changes.
FOR THIS PROMPT
A. Inspect current implementation.
B. State the deficiencies relevant to this prompt.
C. State the implementation plan.
D. Make the required changes.
E. Add/update tests.
F. Run targeted tests.
G. Run the entire regression suite.
H. Run repository sanity/preflight checks.
I. Report:
- files changed
- architecture introduced
- tests executed and results
- compatibility impact
- unresolved risks
- assumptions
- next-stage dependencies
Do not start solving later prompts unless required to establish a clean interface for the
current stage.