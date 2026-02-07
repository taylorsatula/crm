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

## Initial Voice Bootstrap

The system described above learns incrementally - every summon, every takeover, every rejection teaches the model a little more. But starting from zero is rough. The model has no guidance, so it summons constantly. The human is drowning in takeovers for situations the business has handled a thousand times before. It takes weeks of pain before the directives accumulate enough to be useful.

There's a better way: bootstrap the voice from existing communications before the model ever talks to a customer.

### The Concept

Most businesses already have years of customer communications sitting in their SMS history and sent folder. These are organic interactions - real situations, real responses, real voice. An owner who's been texting customers for a decade has demonstrated thousands of times how the business talks. That's gold.

A one-time bootstrap script ingests this archive and extracts:
1. **Baseline directives** - The rules and patterns that govern business communication
2. **Exemplar interactions** - Shining examples with explanatory annotations

The model starts day one with a foundation. It still learns incrementally from new interactions, but it's not starting from nothing.

### Prior Art

This approach borrows from several existing implementations:

**[LLMMe](https://github.com/pizzato/LLMMe)** - Trains a personal LLM on Gmail archives. Uses Google Takeout to export emails, then converts the mbox file into prompt/response pairs (incoming message → user's reply). The key insight: the structure of email threads naturally provides input/output pairs for learning response patterns.

**[MimickMyStyle_LLM](https://github.com/Amirthavarshini-Dhanavel/MimickMyStyle_LLM)** - Fine-tunes Llama on writing samples. Analyzes text for lexical patterns, syntactic features, grammatical distribution, and readability characteristics. Generates a "style summary" that conditions future outputs. Requires ~3,000+ words for effective analysis.

**[Few-shot prompting for voice cloning](https://relevanceai.com/docs/example-use-cases/few-shot-prompting)** - Rather than fine-tuning, uses example messages in the prompt to teach the model the expected tone and structure. Works well with a knowledge search that retrieves similar past responses for each new input.

**Style extraction pipeline** (from [Nina Panicker's approach](https://blog.ninapanickssery.com/p/how-to-make-an-llm-write-like-someone)) - Feed 5+ writing samples to an LLM, ask it to describe the style, then use that description in the system prompt. The model learns in-context from the examples that "the assistant responds in this characteristic style."

### Data Sources

**SMS threads** - The richest source. Text messages are informal, situation-specific, and capture how the business actually talks (not how it thinks it should talk). Export from the business phone or messaging platform.

**Outbound emails** - More formal but still valuable. Captures how the business handles scheduling confirmations, follow-ups, and written communications. Can be exported via provider or Google Takeout.

**Both sources together** give the model range - it learns when to be casual and when to be professional.

### The Bootstrap Process

```
1. INGEST
   - Load SMS export (CSV or JSON from messaging platform)
   - Load email archive (mbox or provider export)
   - Filter to outbound messages only (we're learning the business voice, not customer voice)
   - Pair with context where available (what was the customer's message?)

2. ANALYZE
   - Feed message corpus to LLM in batches
   - Extract style characteristics:
     - Greeting patterns ("Hey!" vs "Hi [Name]," vs no greeting)
     - Sign-off patterns ("Thanks!" vs "-Taylor" vs nothing)
     - Sentence structure (short punchy vs explanatory)
     - Vocabulary preferences (words used, words avoided)
     - Emoji/punctuation usage
     - Formality gradient by situation type

3. CATEGORIZE
   - Group messages by situation type:
     - Scheduling/availability
     - Confirmations
     - Rescheduling
     - Complaints/issues
     - Follow-ups
     - Payment/invoicing
   - Identify patterns within each category

4. SYNTHESIZE
   - Generate baseline directives from patterns
   - Select exemplar messages for each category
   - Annotate exemplars with explanatory notes

5. OUTPUT
   - Structured directive file (same format as distillation output)
   - Exemplar library with annotations
   - Confidence baseline (model starts with guidance, not from zero)
```

### Exemplar Format

Exemplars are complete message examples with annotations explaining why they work. They serve as few-shot examples during inference and as reference material for future distillation.

```markdown
### Exemplar: Scheduling Availability

**Situation**: Customer asking about open slots
**Customer message**: "Do you have anything next week?"
**Response**: "Thursday at 9 or Friday at 2 work?"

**Why this works**:
- Offers specific options rather than "let me check"
- Two choices, not overwhelming
- Question format invites response
- No unnecessary pleasantries - gets to the point
- Matches casual tone of the question
```

```markdown
### Exemplar: Damage Complaint

**Situation**: Customer reporting property damage
**Customer message**: "Your guys broke my sprinkler head"
**Response**: "I'm really sorry to hear that. I'll swing by tomorrow morning to take a look and we'll make it right. Does 9am work?"

**Why this works**:
- Immediate empathy without defensiveness
- Personal accountability ("I'll swing by", not "someone will")
- Concrete next step with specific time
- Commits to resolution without admitting liability
- Doesn't over-apologize or grovel
```

### Implementation

The bootstrap runs as a standalone script, not part of the main application. It's a one-time operation (or occasional re-run if the archive grows significantly).

```
python scripts/bootstrap_voice.py \
  --sms-export ./data/sms_export.csv \
  --email-export ./data/email.mbox \
  --output ./data/baseline_voice.json
```

The output file contains:
- `directives`: Array of baseline rules (same schema as distillation output)
- `exemplars`: Array of annotated example interactions
- `style_summary`: Prose description of the business voice
- `metadata`: Source stats, generation timestamp, model used

This file is loaded when the system starts and provides the initial context for customer conversations. Subsequent distillation runs build on top of it evolutionarily.

### Why This Matters

Without bootstrap:
- Model starts with zero guidance
- First weeks are constant summons
- Human is overwhelmed
- Directives accumulate slowly
- Full autonomy takes months

With bootstrap:
- Model starts with baseline competence
- Common situations handled from day one
- Summons reserved for genuinely novel cases
- Human sees immediate value
- Full autonomy in weeks, not months

The archive represents years of implicit training. The bootstrap makes it explicit.

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

### Bootstrap-Specific

- What's the minimum corpus size for effective bootstrap? (MimickMyStyle suggests 3,000+ words)
- How do we handle multi-person archives? (Owner vs office manager vs tech - different voices)
- Should bootstrap output be human-reviewed before going live?
- How do we get SMS exports from common business phone platforms?
- Email export format standardization (mbox vs provider-specific)
- How do bootstrap exemplars interact with distillation exemplars over time?
- Should the bootstrap script support incremental updates or just full regeneration?
