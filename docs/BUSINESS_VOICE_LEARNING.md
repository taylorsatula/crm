# Business Voice Learning

When you hire a new office manager, they don't know how your business talks to customers. They're too formal, or too casual, or they say "unfortunately" when you'd never use that word. So you chaperone them. You review their emails before they go out. You take over the phone when a conversation gets tricky. Over time, they pick up on the patterns - how you greet regulars, how you handle complaints, when to be brief and when to explain. Eventually, you trust them to handle most things on their own, and they only pull you in for the genuinely hard stuff.

This system does the same thing for an LLM.

The model starts cautious - when it's confident, it handles customer messages autonomously; when it's uncertain, it stops and summons you instead of guessing. When you take over, your response becomes training data. Periodically, all those interactions get distilled into explicit guidance: "lead with empathy on complaints," "use 'I' not 'we' for accountability," "don't over-explain pricing." That guidance gets injected into future conversations, the model's confidence grows, and it needs you less.

The goal is for you to train yourself out of the loop.

The distillation is where the learning happens. After enough interactions accumulate - takeovers, rejections, approvals - they get sent as a batch to a larger model that reviews them as a cluster, looking for patterns. The output is explicit directives that get added to the model's context for future conversations. More on this in the Distillation section below.

The confidence piece is key. Before responding to any customer message, the model runs a quick self-assessment: Is this request clear? Do I have the information I need? Are there emotional, legal, or unusual factors at play? Does my guidance cover this situation? That assessment produces a confidence score. Above the threshold, the model responds. Below it, the model stays quiet and pings you. This isn't you reviewing drafts and rejecting bad ones - the model itself recognizes "I don't know how to handle this" and hands you the controls before saying something wrong.

---

## Concept

### The Problem

When an LLM handles customer communications, it brings generic patterns - corporate-speak, over-formality, or mismatched tone. Every business has its own voice. Training this voice traditionally requires fine-tuning, which is expensive and inflexible.

### The Solution: Text-Based LoRA

Instead of adjusting model weights, we adjust what goes into the prompt:

1. **Operate** - Model handles customer conversations with confidence-gated autonomy
2. **Capture** - Log interactions; human takeovers are the highest-signal training data
3. **Distill** - Periodically synthesize patterns into directives
4. **Inject** - Include directives in the system prompt for future interactions

### The Elegant Part: Self-Improvement

As directives accumulate, the model's confidence in handling edge cases grows. Situations that once triggered a summon become handleable because the model now has explicit guidance.

Early: Model summons frequently → Human handles → Patterns distilled → Directives grow
Later: Model handles situations it previously punted on → Summons become rare

The human trains themselves out of the loop.

---

## Inspiration: MIRA's Implementation

The `botwithmemory` repo implements a similar system for personal assistant interactions:

- **FeedbackExtractor** - Extracts signals from each conversation segment
- **PatternDetector** - Synthesizes patterns from accumulated signals
- **DirectiveWriter** - Writes evolved directives back into context

Key design from MIRA's pattern synthesis:
- **Evolutionary, not replacement** - Each distillation takes previous directives as input
- **Operations**: reinforce (add confidence), refine (more specific), revise (contradicted by evidence), add new
- **Sliding window** - Previous synthesis output feeds into next run for continuity

### Differences for CRM

| Aspect | MIRA | CRM |
|--------|------|-----|
| Signal source | Self-extracted from conversation dynamics | Human feedback on customer interactions |
| Relationship | 1:1 with single user | 1:many with customers |
| Learning target | "How Taylor likes to work" | "How the business talks to customers" |

---

## Confidence-Gated Autonomy

The model runs a "subconscious" confidence check before responding:

- **High confidence** → Respond autonomously
- **Low confidence** → Don't respond, summon the human

This isn't the human rejecting a draft. The model itself recognizes uncertainty and asks the human to take over before saying something wrong.

### Example: Routine Request

```
CUSTOMER: "Do you have anything on Thursday the 6th?"

MODEL: [confidence: 0.84 — clear request, data available]
       "Yes, we have 8:00am open. Want it?"

CUSTOMER: "Yes."

MODEL: [confidence: 0.99 — simple confirmation]
       "Done! See you Thursday at 8."
```

### Example: Edge Case → Summon

```
CUSTOMER: "Which team came to my house yesterday?"

MODEL: [confidence: 0.90 — factual lookup]
       "That was Mike & Bob. How can I help?"

CUSTOMER: "Someone spilled lipstick in my white Valentino bag!"

MODEL: [confidence: 0.13 — angry customer, liability, no guidance for this]
       >>> SUMMON HUMAN <<<

--- Human receives notification with full conversation context ---

HUMAN WRITES:
       "I'm so sorry to hear that. I will stop by this afternoon
        to see it in person. Between now and then I'll speak with
        the team lead so I'm fully informed when I arrive."

MODEL: [sends human's response verbatim]

CUSTOMER: "Thank you for your prompt reply. I will be waiting."

MODEL: [confidence: 0.51 — simple acknowledgment, still cautious given context]
       "You're welcome. We'll text you when we're on our way."
```

---

## Feedback Signals

### Signal Hierarchy

| Signal | Value | What It Captures |
|--------|-------|------------------|
| Autonomous (unreviewed) | Low | "This was acceptable" (implicit) |
| Autonomous (reviewed, approved) | Medium | "This was good" |
| Rejection + required feedback | High | "This was wrong because X" |
| Summon + human takeover | Highest | "This is exactly right for hard situations" |

Thumbs down always requires written feedback - "this was bad" alone teaches nothing.

### Why Summons Are Gold

When the model summons:
1. It recognized its own uncertainty
2. The situation is by definition an edge case
3. The human's response is the canonical answer to a hard question
4. Both parties are present - context is fresh

The human takeover captures exactly how the business handles difficult situations.

---

## Distillation

Feedback accumulates over time - takeovers, rejections with explanations, approved responses. Once enough interactions have collected (the threshold is configurable), they're sent as a batch to a larger model for synthesis. This model reviews the cluster as a whole, looking for patterns: What situations triggered summons? How did the human handle them? What got rejected and why? What consistently worked?

The output is a set of explicit directives - clear guidance derived from real experience. These directives are not immediately live. The human reviews the synthesis output, approves it as-is, or modifies it before it takes effect. Once approved, the directives get injected into the context window for all future customer interactions. The next time a similar situation arises, the model sees "here's how we handle damage claims" or "here's our tone for scheduling" and can respond with confidence instead of uncertainty. The situation that was a 0.13-confidence summon last month becomes a 0.75-confidence autonomous response because there's now a directive covering it.

### The Process

1. Gather completed conversations (prioritizing summons and rejections)
2. Feed to LLM along with previous directives (evolutionary, not replacement)
3. LLM analyzes patterns and evolves directives:
   - **Reinforce** - Pattern confirmed, increase confidence
   - **Refine** - Make existing pattern more specific/nuanced
   - **Revise** - Update pattern contradicted by new evidence
   - **Add** - New pattern from clear signals
4. Updated directives stored and injected into future interactions

### Example Output

After the Valentino bag incident gets distilled:

```markdown
### Handling Damage Claims
- Lead with empathy, not defensiveness
- Offer concrete next step ("I'll stop by") rather than generic apology
- Use "I" not "We" - personal accountability
- Don't admit fault or promise compensation in writing
```

Next time a damage claim arrives, the model has guidance. Confidence goes up. Fewer summons.

---

## Scope

**In scope:** One unified business voice learned from all customer interactions.

**Out of scope:** Per-customer customization. The Spongebob-loving tipper is a note on their customer record, not part of the business voice.

---

## Conversation Boundaries

Each customer exchange is tracked as a conversation with its own UUID. This cleanly separates:
- The exchange itself (messages back and forth)
- The outcome (autonomous vs summoned)
- What gets fed to distillation

---

## Things to Talk About Later

- What triggers distillation? Time-based, volume-based, manual?
- How does the model compute confidence? Prompted self-assessment?
- What's the confidence threshold, and who controls it?
- Database schema for conversations and messages
- How does the human get notified on summon?
- Async review of autonomous conversations - is this needed?
- Distillation prompt design (can draw from MIRA's prompts)
- Where this fits in the implementation phases
- How directives get versioned/rolled back if distillation goes wrong
