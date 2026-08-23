# ParcelPilot — Architecture Note
                         ┌──────────────────────────┐
                         │       USER / CSM         │
                         │  Support Agent / Manager │
                         └────────────┬─────────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │       STREAMLIT UI       │
                         │          app.py           │
                         │                          │
                         │ • Chat interface         │
                         │ • User selection         │
                         │ • Evidence display       │
                         │ • Tools used             │
                         │ • Scan for Issues         │
                         │ • Confirm / Reject       │
                         └────────────┬─────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │       UI INTEGRATION LAYER      │
                    │       src/ui/integration.py     │
                    │                                 │
                    │ • Session state                 │
                    │ • run_investigation()           │
                    │ • confirm_action()              │
                    │ • reject_action()               │
                    └───────────────┬─────────────────┘
                                    │
                                    ▼
                    ┌─────────────────────────────────┐
                    │          LANGGRAPH AGENT        │
                    │                                 │
                    │        START → AGENT            │
                    │                   │             │
                    │             tool calls?         │
                    │              /       \           │
                    │            YES       NO          │
                    │             │         │          │
                    │             ▼         ▼          │
                    │           TOOLS      END         │
                    │             │                    │
                    │             └──→ AGENT           │
                    │                                 │
                    │ • Explicit state                 │
                    │ • Max 8 iterations               │
                    │ • Multi-step investigations      │
                    │ • Authenticated user context     │
                    └───────────────┬─────────────────┘
                                    │
                                    ▼
                    ┌─────────────────────────────────┐
                    │       AUTHORIZATION LAYER       │
                    │                                 │
                    │        auth.py                   │
                    │        permissions.py            │
                    │                                 │
                    │ • User identity                  │
                    │ • Role                           │
                    │ • Permission checks               │
                    │ • Audit logging                  │
                    │                                 │
                    │ Authorization occurs BEFORE      │
                    │ backend access                   │
                    └───────────────┬─────────────────┘
                                    │
                     ┌──────────────┼──────────────┐
                     │              │              │
                     ▼              ▼              ▼
             ┌──────────────┐ ┌──────────────┐ ┌───────────────┐
             │   DOCUMENT   │ │  STRUCTURED  │ │   MONITORING  │
             │    SEARCH    │ │    LOOKUP    │ │     TOOL      │
             └──────┬───────┘ └──────┬───────┘ └───────┬───────┘
                    │                │                 │
                    ▼                ▼                 ▼
             ┌──────────────┐ ┌──────────────┐ ┌───────────────┐
             │   ChromaDB   │ │    SQLite    │ │   Monitoring  │
             │              │ │              │ │    Engine     │
             │ PDF chunks   │ │ accounts     │ │               │
             │ embeddings   │ │ orders       │ │ deterministic  │
             │ metadata     │ │ tickets      │ │ issue rules   │
             └──────┬───────┘ │ escalations  │ └───────┬───────┘
                    │          └──────────────┘         │
                    ▼                                   ▼
             ┌──────────────┐                   ┌───────────────┐
             │ SUPPLIED PDF │                   │ Operational   │
             │ DOCUMENTS    │                   │ Data          │
             │              │                   │               │
             │ Agreements   │                   │ Orders        │
             │ SOPs         │                   │ Tickets       │
             │ Policies     │                   │ Accounts      │
             │ Product docs │                   └───────────────┘
             └──────────────┘

## 1. Agent Design

ParcelPilot uses a LangGraph agent built around a simple, bounded loop:

```
START → agent → tools → agent → (tools again, or → END)
```

At each `agent` step, the LLM sees the conversation, the authenticated user's identity/role, and the results of any tools called so far, and decides whether it has enough evidence to answer or needs another tool call. A hard cap (`MAX_TOOL_ITERATIONS = 8`) prevents runaway loops — if the cap is hit, the agent returns a transparent partial result rather than failing silently or guessing.

I chose LangGraph over a hand-rolled loop because the assessment explicitly asks for multi-step, multi-tool reasoning, and LangGraph makes that control flow explicit and inspectable (state, not just a prompt chain) — which also made it straightforward to unit-test with a deterministic fake model instead of depending on a live API for every test run.

The agent never accesses SQLite or ChromaDB directly — it only sees the five tools below. This keeps the security boundary (see §5) outside the LLM's control.

## 2. Tool Design

Three required categories, split into five concrete tools rather than one generic "do anything" tool:

| Tool | Category | Purpose |
|---|---|---|
| `search_documents` | Document search | Retrieves relevant chunks from policies, SOPs, product docs, and customer agreements, tagged with source type, authority, and status (current/deprecated) |
| `lookup_account` / `lookup_order` / `lookup_ticket` | Structured-data lookup | Query the SQLite tables converted from the supplied Excel workbook |
| `create_escalation` | State-changing action | Creates an escalation row — but only after explicit user confirmation (§4) |

I deliberately split lookups into specific functions (`lookup_order`, not a generic `query_operational_data`) rather than one flexible query tool. A generic tool is more "elegant" but harder to secure — permission checks and audit logging are much simpler to reason about when each tool has one clear responsibility and one clear permission it requires.

## 3. Document and Structured-Data Handling

**Documents (RAG):** The six supplied PDFs are chunked and embedded into ChromaDB. Each chunk carries metadata — `document`, `source_type` (policy / SOP / customer_agreement / product_doc), `authority`, `status` (current / deprecated), `effective_date` — so retrieval returns not just text but *how much to trust it*.

**Structured data:** The Excel workbook (Accounts, Orders, Tickets, README) is loaded into SQLite at startup rather than queried directly from the spreadsheet. This gives the agent real queryable/joinable tables, makes the lookup tools testable in isolation, and matches how this data would actually be served in production (an operational database, not a spreadsheet). The README sheet's stated snapshot time is used as the reference "now" for any time-based question (SLA breaches, "how late is this pickup"), rather than the system clock.

## 4. Source Reliability and Conflict Handling

This was the core design problem the assessment calls out: *"customer-specific agreements may override general policies, and historical ticket resolutions may contain incorrect guidance."*

The agent retrieves evidence first, then applies a precedence rule as a separate step (kept in its own module rather than baked into retrieval, so it can be reasoned about and tested independently):

1. Signed customer agreement (e.g., Northstar Enterprise Agreement)
2. Current support policy / current SOP
3. Product operations / known-issues documentation
4. Historical tickets — **context only, never authoritative**

Critically, the agent does not just silently pick the highest-authority source and discard the rest — when two retrieved sources genuinely conflict, it names the conflict in its answer and explains which one it applied and why (e.g., *"the Northstar agreement specifies X, while the general policy specifies Y; because the agreement takes precedence for this account, I applied X"*). This was a deliberate product choice: a system that hides disagreement between sources is more dangerous than one that surfaces it, because it fails silently.

Deprecated documents (the v2 policy) are tagged `status: deprecated` and excluded from being treated as current guidance even if they're semantically the most similar match to a query.

## 5. Access Control

Authorization is enforced in Python at the tool layer, before any backend call — not via prompt instructions to the LLM. Every tool call requires an explicit authenticated user (`user_id`, `role`, `permissions`); the permission check happens first, and only on success does the tool reach ChromaDB or SQLite. Denied calls are logged (user, role, permission requested, tool, allowed/denied, timestamp) without ever touching the underlying data — this was tested directly with spies to prove the backend is genuinely short-circuited, not just told "no" after the fact.

Mock roles: `support_agent`, `support_manager`, `admin`, each with a defined permission set (e.g., escalation creation is restricted to manager/admin).

## 6. Confirmation Before Actions

State-changing requests (escalations) never execute directly from a natural-language request. The agent investigates, prepares a typed `PendingAction` (ticket, reason, priority, requesting user), and returns a unique confirmation ID with `confirmation_required = true`. Only an explicit `confirm_action(confirmation_id, user)` call — re-checked for authorization at confirmation time, not just at request time — executes `create_escalation`. Confirmations are single-use and time-limited, so a stale or replayed confirmation can't silently fire an action later.

## 7. Major Technical Trade-offs

- **In-process confirmation state, not a persistent store.** Pending actions live in memory rather than a database table with its own durability guarantees — acceptable for an assessment/demo, but a production version would need this to survive a server restart.
- **SQLite over a real relational service.** Fine for the given data volume and matches the assessment's scope; a production ParcelPilot would use a managed DB with proper concurrency handling.
- **LLM makes the final precedence call, guided by rules, not hard-coded per-record.** This was intentional — the assessment explicitly warns against hard-coding answers for specific IDs, since it will be tested against other records. The trade-off is that correctness depends on retrieval quality and prompt discipline rather than a deterministic lookup table, which is why source-conflict test cases were prioritized during evaluation.
- **Chose the internal support/operations chatbot over the customer-facing one.** This surfaces more of the assessment's harder requirements (multi-tool investigation, role-based access, escalation) in one system, at the cost of not building the customer-facing surface at all this round.
