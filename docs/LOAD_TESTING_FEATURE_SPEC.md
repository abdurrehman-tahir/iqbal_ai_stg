# IqbalAI Load Testing Feature Specification (Tool-Agnostic)

## 1) Purpose
This document specifies the end-to-end load/regression testing feature implemented for IqbalAI, including scenarios, input data contracts, runtime state handling, loop semantics, assertions, and report outputs.

This specification is intentionally **tool-agnostic** so another AI/system can implement, extend, or consume it without coupling to any specific execution platform.

---

## 2) System Scope
The feature validates critical user journeys across authentication, conversation creation, document ingestion, retrieval-augmented chat, lesson generation, and student lesson Q&A.

Core capabilities covered:
- Multi-user authentication and dashboard reachability
- Teacher critical path (conversation → ingest → poll → chat → finalize → save)
- Student lesson Q&A depth/concurrency
- Sequential long-thread chat stability
- Repeated ingestion stability
- Content-quality benchmark checks
- Concurrent teacher end-to-end flows

---

## 3) Architectural Context

```text
[Test Orchestrator]
  ↓
[Scenario Chain Executor]
  ↓
[Auth + Chat + RAG + Lesson API Layer]
  ↓
[Service Layer]
  ↓
[(SQL DB)] + [File Storage] + [RAG Index/Vector State]
```

### Data flow
1. Scenario inputs are loaded from one JSON file (array of test case objects).
2. Per-iteration fields map into runtime variables.
3. Requests execute in deterministic chains.
4. Loops are controlled by runtime counters and terminal conditions.
5. Response IDs (conversation/thread/task/lesson/etc.) are captured and propagated.
6. Step-level metrics and outcomes are appended to a structured report artifact.

---

## 4) Scenario Catalog (T1–T8)

## T1 — Auth & Dashboard
**Goal:** Verify sign-in/logout and root dashboard availability.

**Flow:**
1. Login with user credentials
2. Access root dashboard
3. Logout

**Primary checks:**
- Login success
- Dashboard response success
- Logout success

---

## T2 — Teacher Full Flow (Critical Path)
**Goal:** Validate full teacher workflow from uploaded document to saved lesson.

**Flow:**
1. Login as teacher
2. Create conversation
3. Ingest document
4. Poll ingestion status until completion (if async path)
5. Chat in RAG context (multi-message sequence)
6. Retrieve finalized lesson state
7. Save lesson with `rag_thread_id`

**Primary checks:**
- Ingest completed
- Chat loop completed for all messages
- Save lesson completed (or expected validation failure captured)

---

## T3 — Student Lesson Chat (Concurrent)
**Goal:** Simulate multiple students asking lesson-related questions.

**Flow:**
1. Login as student
2. Loop through messages against lesson Q&A endpoint using `lesson_id`

**Primary checks:**
- All message steps return acceptable status
- No session/identity bleed between users

---

## T4 — Teacher Sequential RAG
**Goal:** Stress long-context teacher chat sequence in one thread.

**Flow:**
1. Login
2. Create conversation
3. Ingest document (+ optional poll)
4. Execute ordered chat message sequence in same thread

**Primary checks:**
- Thread continuity
- Stable response behavior over depth

---

## T5 — Student Sequential Chat
**Goal:** Validate deep student Q&A conversation over one lesson.

**Flow:**
1. Login student
2. Sequentially send 5–10+ lesson questions with same `lesson_id`

**Primary checks:**
- Full sequence completion
- No degradation/failure spikes at deeper turns

---

## T6 — Repeated Ingest Stability
**Goal:** Validate ingestion stability and consistency under repeated uploads.

**Flow:**
1. Login teacher
2. Repeat N times:
   - Create conversation
   - Ingest same document
   - Poll if needed

**Primary checks:**
- Consistent completion rate
- Comparable output characteristics (`chunks/pages/documents` where available)

---

## T7 — RAG Quality Benchmark
**Goal:** Regression-style semantic quality check.

**Flow:**
1. Login teacher
2. Create conversation
3. Ingest document (+ optional poll)
4. Ask benchmark question(s)
5. Evaluate keyword expectations

**Primary checks:**
- Required keyword hit count
- Content relevance trend across runs

---

## T8 — Teacher Full Flow Concurrent
**Goal:** Run multiple teacher critical paths in parallel-like iteration mode.

**Flow:**
Same as T2, but dataset includes multiple teacher accounts/cases.

**Primary checks:**
- End-to-end completion per teacher case
- Failure distribution by step
- Step-level latency comparison across users

---

## 5) Input Data Contracts
Each scenario uses a single JSON array file; each element is one test case.

## 5.1 Common fields
- `case_id` (string): unique case identifier
- `scenario_tag` (string): scenario grouping key
- `useremail` (string): account email
- `password` (string): account password

## 5.2 Teacher flow fields (T2/T4/T6/T7/T8)
- `doc_path` (string): absolute document path
- `messages` (string[]): ordered chat prompts (not required for pure ingest repeat)
- `focus_area` (string): lesson save metadata
- `grade_level` (string|number): lesson save metadata
- `lesson_title` (string): lesson save title
- `lesson_summary` (string): lesson summary
- `lesson_content_fallback` (string): fallback save content
- `repeat_ingest` (int): repetition count for T6
- `expected_contains` (string[]): keyword expectations for T7
- `save_lesson` (bool): whether lesson-save step should be executed

## 5.3 Student flow fields (T3/T5)
- `lesson_id` (string|number): existing lesson identifier
- `messages` (string[]): ordered student prompts
- `allow_rag` (bool): optional Q&A behavior flag

## 5.4 Non-functional field
- `_comments` (object): optional metadata for human guidance, ignored by runtime.

---

## 6) Runtime Variable Model
Runtime variables are used to connect dynamic outputs to later steps.

Core variable set:
- Identity/session: `useremail`, `password`
- Threading/state: `conversation_id`, `thread_id`, `task_id`, `lesson_id`, `doc_id`
- Loop control: `msg_index`, `messages_json`, `poll_attempt`, `max_poll_attempts`, `ingest_count`, `repeat_ingest`
- Reporting: `scenario_name`, `scenario_report`

### Update principles
1. Capture response IDs as soon as returned.
2. Keep loop counters monotonic.
3. Fail fast on unrecoverable status/error states.
4. Enforce max attempts for polling loops.

---

## 7) Control-Flow Semantics

## 7.1 Message loop
- Convert `messages` input into `messages_json`
- Initialize `msg_index = 0`
- For each iteration:
  - set `current_message = messages[msg_index]`
  - execute chat/Q&A request
  - increment index
  - continue while `msg_index < messages.length`

## 7.2 Ingest polling loop
- Start with ingest request
- If immediate success and `thread_id` present, continue chain
- If processing + `task_id`, poll status endpoint
- Increment `poll_attempt` every poll
- Stop/fail when `poll_attempt >= max_poll_attempts`

## 7.3 Repeated ingest loop
- Maintain `ingest_count`
- Repeat ingest chain while `ingest_count < repeat_ingest`
- Preserve per-iteration report records

---

## 8) Assertions and Acceptance Rules

## 8.1 Minimum assertions per step
- HTTP status in expected set for the step
- Required IDs present when needed by downstream steps
- Loop completion conditions met (messages complete / poll success / repeat target reached)

## 8.2 Scenario-level pass conditions
- **T1:** login + dashboard + logout complete
- **T2/T8:** conversation + ingest + chat sequence + save lesson reach terminal state
- **T3/T5:** all question messages processed for each case
- **T4:** full message depth completed in one thread
- **T6:** `repeat_ingest` target achieved
- **T7:** quality keyword threshold met

---

## 9) Reporting Specification
The feature emits compact structured records suitable for downstream UI/reporting.

## 9.1 Step-level record schema
Each request appends one object to `scenario_report`:
- `ts` (ISO timestamp)
- `req` (step name)
- `code` (HTTP status)
- `rt` (response time ms)
- `ok` (boolean)
- `case_id` (string)

## 9.2 Recommended scenario summary fields (derived)
- `scenario_name`
- `total_steps`, `passed_steps`, `failed_steps`
- `p50/p95 latency` by step
- `ingest_duration_ms`, `finalize_duration_ms`
- `message_count`, `message_success_rate`
- `keyword_hits` (T7)

## 9.3 Export artifacts
Produce two artifacts per run:
1. **Raw event log JSON** (step-level records)
2. **Scenario summary JSON** (aggregated KPIs)

Naming convention example:
- `reports/<scenario>/<run_id>/events.json`
- `reports/<scenario>/<run_id>/summary.json`

---

## 10) Failure Taxonomy
Classify failures for better triage:
- `AUTH_FAILURE`
- `CONVERSATION_FAILURE`
- `INGEST_START_FAILURE`
- `INGEST_TIMEOUT`
- `INGEST_FAILURE`
- `CHAT_FAILURE`
- `FINALIZE_FAILURE`
- `SAVE_LESSON_FAILURE`
- `QUALITY_ASSERTION_FAILURE`
- `DATA_CONTRACT_FAILURE`

Each failed step should include:
- failure category
- endpoint/step
- short error snippet
- case_id + scenario_tag

---

## 11) Data Handling & Safety
- Never log plaintext secrets beyond what is required for runtime execution.
- Do not include full AI responses in compact logs by default (size/privacy); keep short snippets if needed.
- Keep report records bounded for large runs.
- Preserve run reproducibility via fixed case IDs and deterministic scenario names.

---

## 12) Operational Runbook (Tool-Neutral)
1. Select scenario (T1–T8)
2. Provide matching JSON data array
3. Execute with desired iterations/concurrency profile
4. Collect event + summary outputs
5. Feed outputs into downstream analytics/UI

---

## 13) Known Gaps / Extension Points
- Add richer percentile stats and histogram bins per step.
- Add baseline-vs-current comparator for regression alerts.
- Add endpoint-specific SLA thresholds and automatic failure tagging.
- Add cross-run trend reports (daily/weekly).

---

## 14) Versioning
- Spec version: `v1.0`
- Intended use: implementation guidance for another AI/automation system.
