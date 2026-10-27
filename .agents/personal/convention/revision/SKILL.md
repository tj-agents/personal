---
name: revision
description: Write a page designed to be revised and rehearsed - one canonical page per topic, honest status and attribution, a question-to-section map, answers as spoken beats, and follow-up questions to self-test. Use when turning any topic, project or design into material Tommy will revise, rehearse or be questioned on, such as interview prep, a presentation or a design walkthrough.
kind: convention
domain: personal
profile: core
applicability: material Tommy revises or rehearses
requires: docs
provenance: house
---

# Revision pages

A revision page is reread and rehearsed out loud, not read once. Lay it out with `docs:layout`; this
adds what revising needs.

## One page per topic

Everything about one topic lives on one page. An index links to that page's section anchors and never
holds a second write-up. When a topic already has a page, extend it instead of adding a file beside it.

## State the truth before the story

The header table says what is shipped, agreed or proposed, with dates. A "My part" table names what
Tommy did and what others did, so a rehearsed answer never claims someone else's work. Mark Tommy's own
reasoning apart from a recorded decision.

## Map questions to sections

The rehearsal section opens with a `Question | Lead with | Section` table, linking each question Tommy
expects to be asked to the section that answers it.

## Write answers as beats

Each rehearsed answer is a `Beat | Say` table (situation, problem, action, Tommy's part, result) sized
for 60 to 90 seconds, with the numbers to quote. Never a paragraph to memorise.

## Self-test the follow-ups

Each likely follow-up is a `<details>` block with the question as the summary and a few bullet points
as the answer, so it can be answered before it is opened. Finish with a whiteboard diagram and the order
to talk through it.

```markdown
## 8. Rehearse

| Question | Lead with | Section |
| --- | --- | --- |
| Why did the design change? | v1 to v2 | [4](#4-the-redesign-v2) |

| Beat | Say |
| --- | --- |
| **Situation** | The service kept its own copy of a mapping another service owned. |
| **Result** | Design agreed late October; build under way. |

<details>
<summary><b>Why events rather than a synchronous call?</b></summary>

- The legacy product never waits on a new service.
- Cost: the first session lacks the id.
</details>
```
