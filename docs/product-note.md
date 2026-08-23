# ParcelPilot — Product Note

## Which additional client problem I chose, and how I addressed it

I focused on **Problem 2: Trust and Reliability** rather than Problem 1 (Proactive Issue Detection).

The brief is explicit that policies change, contracts can override general rules, and past support answers may be wrong — and that a confidently incorrect answer would quickly kill adoption for an internal support tool. I treated that as the central product risk to design around, not a nice-to-have:

- Every piece of retrieved evidence carries explicit metadata (source type, authority, current/deprecated status) rather than being treated as interchangeable text.
- A precedence rule (customer agreement → current policy/SOP → product docs → historical tickets as context only) is applied as a separate, testable step after retrieval — not folded invisibly into the prompt.
- When two retrieved sources genuinely disagree, the agent **names the conflict explicitly** in its answer instead of silently picking one. I'd rather the support team see "these two sources disagree, here's which one applies and why" than get a clean-sounding answer that hides a real discrepancy.
- Deprecated policy documents are excluded from being treated as current, even when they're the closest semantic match to a query.
- State-changing actions always require explicit confirmation, and that confirmation is re-authorized (not just re-displayed) before execution — so a stale or mistaken "yes" can't silently take an action.

I think this matters more than a wider feature set for a first release: a support tool the team can't trust doesn't get used, regardless of how many tools it has.

## What I'd build next for ParcelPilot

In priority order:

1. **Proactive issue detection (Problem 1)** — an internal dashboard aggregating tickets by recurrence, severity, and SLA proximity, plus cross-customer pattern detection (e.g., "5 accounts affected by the same carrier issue this week"). This is the natural next investment once the reactive agent is trustworthy, and reuses the same structured-data layer already built.
2. **Persistent confirmation and audit storage** — moving pending-action state and audit logs from in-process memory to a real table, so they survive restarts and support real operational review.
3. **Evaluation harness** — a small labeled set of questions (including deliberately conflicting-source cases and unanswerable cases) run automatically against the agent, so regressions in retrieval or reasoning are caught before they reach a support agent.
4. **Account-scoped access for a customer-facing surface** — if ParcelPilot wants to extend this to customers directly, the authorization layer already distinguishes global vs. restricted access; the next step is wiring real per-account scoping so a customer literally cannot retrieve another customer's data.
5. **Human handoff / escalation queue UI** — right now an escalation is a database row; a real workflow would route it to a person with context attached, not just create a record.

## What I intentionally left out of this submission

- **A customer-facing chatbot.** I chose to go deep on the internal support/ops agent rather than build both, since the assessment allows either and the internal agent surfaces more of the hard requirements (multi-tool investigation, role-based access, escalation workflow) in one coherent system.
- **Persistent conversation history across sessions** — each session starts fresh; there's no long-term memory of past conversations with a given user.
- **Real authentication** — users are mocked (role + permission set), as the assessment explicitly allows.
- **The proactive issue-detection dashboard** — scoped out for this round in favor of doing trust/conflict handling thoroughly (see above); it's my top "next" priority.
- **Production-grade persistence for confirmations/audit logs** — currently in-process, as noted in the architecture note's trade-offs section.

## Metric I'd use to judge usefulness

**Percentage of support queries the agent resolves correctly without needing escalation or correction, measured against a labeled evaluation set that includes conflicting-source and unanswerable cases.**

I'd deliberately weight that metric toward *not answering confidently when it shouldn't* — a system that escalates a genuinely ambiguous case is doing its job; a system that answers confidently and wrongly is the failure mode the whole trust-and-reliability design was meant to prevent. So alongside the headline resolution rate, I'd track a secondary "confident-wrong-answer rate" on the same eval set and treat that as the metric that actually gates whether the product is trustworthy enough to expand.
