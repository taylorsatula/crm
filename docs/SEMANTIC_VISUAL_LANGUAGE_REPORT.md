# CRM Semantic Visual Language Report

## Scope

This report proposes a semantic visual language for the current web interface in `static/`. It is not an implementation patch and does not propose generic SaaS styling. The goal is to make existing application state, priority, actionability, risk, completion, failure, changed data, confirmation, and attention easier to perceive.

Current evidence:

- `static/index.html:27-35` defines the primary task surfaces: Today, Customers, Tickets, Invoices, Messages, Catalog, Support.
- `static/styles.css:123-143` gives navigation and active surface state the same black-border language used everywhere else.
- `static/index.html:181-187` and `static/js/dom.js:68-80` make dense rows interactive buttons, but rows do not carry selected state.
- `static/js/views.js:256-270` puts ticket status, confirmation status, clock state, and pending message counts into row text.
- `static/js/views.js:391-418` exposes invoice status, payment state, and action eligibility.
- `static/js/views.js:201-229` exposes message status and the pending-only cancel action.
- `static/js/dom.js:110-160` already has a focused patch-panel workflow layer and submit-disable behavior.
- `static/js/app.js:255-271`, `static/js/app.js:380-407`, and `static/js/app.js:510-521` use the same patch panel for confirmation of destructive or risky actions.
- `static/js/app.js:671-677` loads invoice/message filters but does not currently persist a selected filter state in the DOM.

Live observations from `http://127.0.0.1:8000/`:

- At a 678px viewport, the interface stacks list and detail. This makes hierarchy and continuity even more important because the operator loses the side-by-side spatial relationship.
- The current active nav state, row separators, cluster borders, focused fields, empty states, primary actions, and destructive confirmations all compete using the same high-contrast black-line vocabulary.
- A Today row says `Open job`, but the click path opens the Tickets surface and ticket detail. That is a semantic mismatch that color cannot fix.

## Reference Anchors

- WCAG 2.2 is the current web accessibility baseline for contrast, target size, focus, and non-text UI indicators. Use 4.5:1 as the minimum text contrast target for normal text and 3:1 for essential non-text UI indicators.
- APCA should be used as an additional readability sanity check for small labels, muted text, and colored status chips. It is not the conformance standard for this app unless a later requirement says so.
- Apple HIG color guidance supports color when it communicates status, feedback, continuity, or interactivity, and warns against reusing the same color for different meanings.
- Apple HIG motion guidance supports motion when it conveys feedback, status, instruction, continuity, or causality, and requires a reduced-motion path.
- Nielsen heuristics apply directly here: visibility of system status, recognition rather than recall, consistency, error prevention, user control, and minimalist design.

## Current Root Problem

Root cause identified:
The frontend has strong functional semantics in JavaScript and HTML, but the visual layer has only one primitive: black outline on white.

Causal chain:
Functional state exists in data and labels -> CSS renders most controls, rows, panels, filters, notices, and destructive confirmations with the same contrast and shape -> operators must read every label to know what is active, risky, blocked, complete, or newly changed -> workflow cost rises, especially on mobile and during repetitive office work.

Solution mechanics:
Add a small set of semantic visual tokens, then bind them only to existing state categories: action, selected/current, attention, success, danger, muted/inactive, changed, loading, and task layer.

Not a symptom fix because:
The proposal does not decorate isolated elements. It maps the data model and workflow state already present in `views.js`, `app.js`, and `dom.js` into a consistent visual grammar.

Production considerations:
Every state must remain readable without color. Use text, shape, position, border weight, and ARIA state along with color. Respect `prefers-reduced-motion`. Do not add image assets, large JS, or color-coded surface branding.

Engineering Assertion:
These solutions eliminate the current visual ambiguity at its root: meaningful state exists but is not visually encoded. The proposed system makes state perceivable without adding decorative chrome.

## Foundational Visual Tokens

Use a restrained neutral base with a few semantic accents.

- Canvas: low-glare neutral background, not a branded wash. Meaning: normal workspace.
- Surface: white or near-white task containers. Meaning: current work object.
- Separator: lower-contrast neutral lines. Meaning: grouping, not urgency.
- Strong border: reserved for active layer, primary task boundary, or focus. Meaning: this is the current interaction target.
- Muted text: secondary/supporting facts only. Meaning: helpful but not the next decision.
- Action blue: primary action, current navigation, selected row, focus ring. Meaning: this is where the operator can act or currently is.
- Attention amber: pending, due, estimated, blocked, needs confirmation, incomplete readiness. Meaning: review or resolve before completion.
- Success green: completed, paid, confirmed, healthy, saved. Meaning: done or safe to proceed.
- Danger red: failed, destructive, void/delete, infrastructure error. Meaning: risk, failure, or irreversible change.
- Muted gray: inactive, canceled, void, disabled, empty. Meaning: no current action or historical/non-operative state.
- Changed highlight: brief pale blue or pale green background fade. Meaning: the data on screen just changed because of the user's action.

Do not assign colors to top-level surfaces as brands. Today should not be green, Customers should not be purple, and Invoices should not be a permanent color world. That would encode taxonomy, not state.

## Proposed Touches

### 1. Current Surface Navigation

Apply action-blue text or underline plus a subtle selected background to the active nav button in `static/styles.css:141-143`. Keep the nav otherwise quiet.

- What meaning does it communicate? The current task surface.
- What user uncertainty does it resolve? It answers "Where am I?" without requiring the operator to parse the page heading.
- What state change does it reveal? Surface changes triggered by `setActiveSurface()` in `static/js/app.js:132-144`.
- What action does it make easier or safer? It reduces accidental work on the wrong surface, especially when actions like invoices/messages/tickets have similar list-detail shapes.
- What cognitive burden does it reduce? Navigation recall and reorientation after workflow redirects.
- Is this semantic, or merely decorative? Semantic.

### 2. Selected Dense Row

Add a persistent selected-row state for the row whose object is open in detail. Use a left action-blue rule, light selected background, and `aria-current` or equivalent state where appropriate.

- What meaning does it communicate? This row is the source object for the open detail.
- What user uncertainty does it resolve? It answers "Which list item am I looking at?"
- What state change does it reveal? Opening a customer, ticket, invoice, message, or service.
- What action does it make easier or safer? It makes comparison and next-row selection safer when multiple rows have similar names, as seen in the live customer and ticket lists.
- What cognitive burden does it reduce? Visual backtracking between queue and detail.
- Is this semantic, or merely decorative? Semantic.

### 3. Primary Action

Use a filled action-blue primary button for the single next-best local action in each task context. Preserve secondary buttons as neutral. Avoid marking more than one local action as primary unless there are truly parallel first actions.

- What meaning does it communicate? The recommended next action in the current workflow.
- What user uncertainty does it resolve? It answers "What should I do next from here?"
- What state change does it reveal? N/A.
- What action does it make easier or safer? It speeds common operations such as Book appointment, Use for booking, Record payment, Create invoice when ready, or Save.
- What cognitive burden does it reduce? Action triage inside dense action bands.
- Is this semantic, or merely decorative? Semantic.

### 4. Secondary Actions

Render secondary actions with neutral borders and normal text weight. Keep them visible but below primary action weight.

- What meaning does it communicate? Available but not dominant actions.
- What user uncertainty does it resolve? It distinguishes "possible" from "recommended."
- What state change does it reveal? N/A.
- What action does it make easier or safer? It prevents less common actions like Edit, Add note, or Open customer from competing with the workflow's main action.
- What cognitive burden does it reduce? Repeated scanning of large action bands.
- Is this semantic, or merely decorative? Semantic.

### 5. Destructive And Risk Actions

Use danger-red border/text for irreversible destructive actions like Delete ticket, Delete service, Remove note, and Void invoice. Use amber for reversible interruption actions like Cancel appointment or Cancel message if the business treats those as recoverable; otherwise use danger.

- What meaning does it communicate? The action can remove, void, cancel, or materially disrupt business data.
- What user uncertainty does it resolve? It answers "Is this risky?"
- What state change does it reveal? N/A before click; after confirmation it reveals deletion, voiding, cancellation, or removal through state/status.
- What action does it make easier or safer? It prevents accidental destructive clicks in action bands with many neutral commands.
- What cognitive burden does it reduce? Risk classification by label reading alone.
- Is this semantic, or merely decorative? Semantic.

### 6. Destructive Confirmation Patch

For confirmation patches opened by `confirmAction()` in `static/js/app.js:255-271`, use a danger or attention accent on the patch header and submit button, plus a neutral Cancel button. The body should restate the object and consequence.

- What meaning does it communicate? The operator is in a confirmation state for a risky action.
- What user uncertainty does it resolve? It answers "Am I about to commit the risky action, or am I still in normal editing?"
- What state change does it reveal? The UI has moved from action selection into confirmation.
- What action does it make easier or safer? It makes Cancel visually available as the escape route and makes the committing action unmistakable.
- What cognitive burden does it reduce? Mode confusion inside the same bottom patch host.
- Is this semantic, or merely decorative? Semantic.

### 7. Patch Panel Task Layer

Give `.patch-host` and `.patch-panel` a stronger layer treatment than ordinary clusters: raised shadow or top rule, slightly distinct background, and clear focus transfer. On mobile, treat it as a bottom task sheet. On desktop, keep its right/bottom position but visually above the current surface.

- What meaning does it communicate? A temporary task is active over the current record.
- What user uncertainty does it resolve? It answers "Where did my form open, and what record is it attached to?"
- What state change does it reveal? Opening, saving, canceling, or clearing a workflow patch through `openPatch()` and `clearPatch()`.
- What action does it make easier or safer? It protects against editing the background record accidentally while the patch is active.
- What cognitive burden does it reduce? Layer and mode tracking.
- Is this semantic, or merely decorative? Semantic.

### 8. Patch Panel Motion

Use a short slide/fade for patch entry and exit. The motion should follow physical causality: bottom sheet rises from the bottom on mobile; side/bottom panel settles into its anchored position on desktop. Disable or reduce via `prefers-reduced-motion`.

- What meaning does it communicate? A temporary workflow layer has appeared or left.
- What user uncertainty does it resolve? It shows where the task came from and where focus moved.
- What state change does it reveal? Patch opened or closed.
- What action does it make easier or safer? It helps the operator retain context while moving from list/detail into form entry.
- What cognitive burden does it reduce? Mode-switch disorientation.
- Is this semantic, or merely decorative? Semantic.

### 9. Form Focus Ring

Replace browser-default focus ambiguity with a consistent action-blue focus ring that is clearly visible around inputs, selects, textareas, buttons, and dense rows. The focus indicator must not be clipped by containers.

- What meaning does it communicate? This is the current keyboard/input target.
- What user uncertainty does it resolve? It answers "Where will typing or Enter act?"
- What state change does it reveal? Focus movement.
- What action does it make easier or safer? It supports keyboard use, fast data entry, and correction in long patch forms.
- What cognitive burden does it reduce? Cursor and focus hunting.
- Is this semantic, or merely decorative? Semantic.

### 10. Validation And Required Fields

Use danger red only for invalid fields after interaction or failed submit, not preemptively on all required fields. Use a short inline error message and preserve native required semantics.

- What meaning does it communicate? This specific field blocks submission.
- What user uncertainty does it resolve? It answers "What must I fix?"
- What state change does it reveal? Field or form moved from unvalidated to invalid.
- What action does it make easier or safer? It directs correction to the exact field instead of forcing the operator to infer from a global error.
- What cognitive burden does it reduce? Error diagnosis.
- Is this semantic, or merely decorative? Semantic.

### 11. Submit-In-Progress State

When `openPatch()` disables submit and cancel controls in `static/js/dom.js:142-151`, add a visual in-progress state: button label like Saving, subtle spinner/dot, or progress affordance. Keep controls disabled.

- What meaning does it communicate? The request is already in flight.
- What user uncertainty does it resolve? It answers "Did my click register?"
- What state change does it reveal? Idle form -> submitting.
- What action does it make easier or safer? It prevents double submission and impatient repeat clicks.
- What cognitive burden does it reduce? Waiting uncertainty.
- Is this semantic, or merely decorative? Semantic.

### 12. Global Notice Bar

Split `.notice` into success, error, and informational variants. Success should be brief and calm. Error should be red-accented and persistent enough to read. Avoid showing request IDs in normal UI.

- What meaning does it communicate? Result of the last system action.
- What user uncertainty does it resolve? It answers "Did it work?"
- What state change does it reveal? API action completed, failed, or requires attention.
- What action does it make easier or safer? It lets the operator continue after success or recover after failure.
- What cognitive burden does it reduce? Outcome verification.
- Is this semantic, or merely decorative? Semantic.

### 13. Loading State

Replace plain `Loading` empty text with a low-motion skeleton row or quiet progress row inside the affected list/detail container. Do not animate globally unless the whole app is blocked.

- What meaning does it communicate? This specific region is waiting on data.
- What user uncertainty does it resolve? It answers "What part of the screen is updating?"
- What state change does it reveal? Idle or stale data -> pending request.
- What action does it make easier or safer? It discourages acting on stale context during refresh.
- What cognitive burden does it reduce? Waiting and stale-data ambiguity.
- Is this semantic, or merely decorative? Semantic.

### 14. Empty State

Use muted text and a quiet background only when the empty state is informational. If the empty state implies a next action, pair it with the relevant action, for example Add scope before invoicing.

- What meaning does it communicate? There is no current data in this slot, or the workflow is blocked until data exists.
- What user uncertainty does it resolve? It answers "Is this missing, loading, or intentionally empty?"
- What state change does it reveal? Loaded list/detail with zero items.
- What action does it make easier or safer? It points the operator to the next required input when the absence blocks progress.
- What cognitive burden does it reduce? Empty-vs-broken ambiguity.
- Is this semantic, or merely decorative? Semantic.

### 15. Ticket Status Chips

Convert raw ticket status text in dense rows and fact grids into chips. Use neutral for scheduled, action-blue for in progress/clocked in, success green for completed, muted gray for cancelled, danger red for failed/problem states if introduced.

- What meaning does it communicate? Operational state of the work.
- What user uncertainty does it resolve? It answers "Can this job still be worked, is it underway, or is it done?"
- What state change does it reveal? Ticket status changes from actions such as clock in, clock out, close, cancel, or delete.
- What action does it make easier or safer? It helps operators choose whether to open, close out, invoice, or ignore.
- What cognitive burden does it reduce? Re-reading row text for every ticket.
- Is this semantic, or merely decorative? Semantic.

### 16. Confirmation Status

Use amber for pending/needs confirmation, success green for confirmed, danger red for failed/bounced, muted gray for not required.

- What meaning does it communicate? Customer communication certainty.
- What user uncertainty does it resolve? It answers "Does this appointment need outreach?"
- What state change does it reveal? Confirmation sent, pending, confirmed, or failed.
- What action does it make easier or safer? It makes Schedule confirmation and message follow-up easier to prioritize.
- What cognitive burden does it reduce? Searching row meta for `confirmation: pending`.
- Is this semantic, or merely decorative? Semantic.

### 17. Clock State

Use action-blue or green emphasis for in-progress clock state, neutral/muted for not started, and success green for completed/clocked out. Pair with text.

- What meaning does it communicate? Technician time state.
- What user uncertainty does it resolve? It answers "Is someone currently on this job?"
- What state change does it reveal? Clock in and clock out actions in `static/js/app.js:408-417`.
- What action does it make easier or safer? It helps avoid duplicate clock-in/out actions and identifies active work.
- What cognitive burden does it reduce? Monitoring active field work.
- Is this semantic, or merely decorative? Semantic.

### 18. Price Estimated

Render `Price estimated: Yes` as amber attention. Render `No` as neutral or success only when the final price is locked by scope/invoice.

- What meaning does it communicate? The price is uncertain.
- What user uncertainty does it resolve? It answers "Can I confidently invoice this?"
- What state change does it reveal? Estimate flag changes in appointment editing.
- What action does it make easier or safer? It encourages scope/price review before sending invoice.
- What cognitive burden does it reduce? Remembering which tickets still need price confirmation.
- Is this semantic, or merely decorative? Semantic.

### 19. Invoice Readiness

Use amber for blocked readiness states such as `Add scope before invoicing`, action-blue for `Ready total`, and success green for existing paid invoice summaries.

- What meaning does it communicate? Whether the ticket can become an invoice.
- What user uncertainty does it resolve? It answers "What prevents invoicing?"
- What state change does it reveal? Scope added, invoice created, invoice paid.
- What action does it make easier or safer? It points the operator to Add scope or Create invoice at the right moment.
- What cognitive burden does it reduce? Invoicing eligibility analysis.
- Is this semantic, or merely decorative? Semantic.

### 20. Invoice Status And Balance

Use neutral for draft, action-blue for sent/open, amber for partial or balance due, success green for paid, muted gray for void. Emphasize nonzero balance more than subtotal/tax.

- What meaning does it communicate? Revenue state and collection priority.
- What user uncertainty does it resolve? It answers "Is money still owed?"
- What state change does it reveal? Send invoice, record payment, void invoice, or paid event.
- What action does it make easier or safer? It prioritizes Record payment, Send invoice, or no action.
- What cognitive burden does it reduce? Mental subtraction between total and paid.
- Is this semantic, or merely decorative? Semantic.

### 21. Message Status And Filters

Render Due and Failed as attention/danger, Pending as neutral or action-blue when selected, Sent as success, Canceled as muted. Add a selected state to filter buttons after `loadMessages(filter)`.

- What meaning does it communicate? Message delivery and queue state.
- What user uncertainty does it resolve? It answers "Which message queue am I looking at, and what needs intervention?"
- What state change does it reveal? Filter changed; message sent, failed, pending, due, or canceled.
- What action does it make easier or safer? It makes failed-message triage and pending cancellation easier.
- What cognitive burden does it reduce? Remembering the currently loaded filter and interpreting raw status strings.
- Is this semantic, or merely decorative? Semantic.

### 22. Invoice Filters

Add selected state to invoice filter controls after `loadInvoices(filter)`. Use stateful segmented-control styling, not unrelated colors for each filter.

- What meaning does it communicate? Which invoice queue is currently loaded.
- What user uncertainty does it resolve? It answers "Am I seeing unpaid, draft, or all invoices?"
- What state change does it reveal? Invoice filter changed.
- What action does it make easier or safer? It prevents acting on an assumed queue that is not actually visible.
- What cognitive burden does it reduce? Filter state recall.
- Is this semantic, or merely decorative? Semantic.

### 23. Primary Address

Render `Primary` on addresses as a small success/selected chip, not plain row text.

- What meaning does it communicate? Default service address.
- What user uncertainty does it resolve? It answers "Which address will booking probably use?"
- What state change does it reveal? Primary address changed.
- What action does it make easier or safer? It makes Use for booking safer when multiple addresses exist.
- What cognitive burden does it reduce? Address selection.
- Is this semantic, or merely decorative? Semantic.

### 24. Customer Attribute Source And Review

For manually created attributes, keep neutral. For future LLM-derived attributes, use a distinct review/changed treatment until approved or accepted. Do not use color to imply truth; use it to imply source/review state.

- What meaning does it communicate? Source and review status of structured customer data.
- What user uncertainty does it resolve? It answers "Is this a normal fact, or does it need review?"
- What state change does it reveal? Attribute created, inferred, reviewed, accepted, or removed.
- What action does it make easier or safer? It prevents unreviewed inferred data from blending into confirmed customer facts.
- What cognitive burden does it reduce? Trust calibration.
- Is this semantic, or merely decorative? Semantic.

### 25. Catalog Active/Inactive

Render Active as success-green status, Inactive as muted gray. Do not make active services look like urgent work; active here means available for selection.

- What meaning does it communicate? Service availability in booking/scope workflows.
- What user uncertainty does it resolve? It answers "Can this service be used now?"
- What state change does it reveal? Toggle active/inactive.
- What action does it make easier or safer? It protects operators from adding inactive catalog items.
- What cognitive burden does it reduce? Catalog scan cost.
- Is this semantic, or merely decorative? Semantic.

### 26. Pricing Type

Use compact neutral chips for fixed, flexible, and per-unit. Avoid strong status colors because pricing type is a category, not urgency.

- What meaning does it communicate? How price is determined.
- What user uncertainty does it resolve? It answers "Will price auto-fill, need manual entry, or depend on quantity?"
- What state change does it reveal? Pricing type changed in catalog editing.
- What action does it make easier or safer? It helps scope-entry operators avoid wrong price assumptions.
- What cognitive burden does it reduce? Remembering service pricing rules.
- Is this semantic, or merely decorative? Semantic.

### 27. Changed Data Feedback

After saves such as Appointment updated, Scope added, Payment recorded, or Service updated, briefly highlight the changed row/fact section and fade back to normal. Use no looping animation.

- What meaning does it communicate? This exact data changed because of the completed action.
- What user uncertainty does it resolve? It answers "What changed?"
- What state change does it reveal? Mutation succeeded and the refreshed area contains new data.
- What action does it make easier or safer? It lets the operator verify the result without rereading the whole page.
- What cognitive burden does it reduce? Post-save audit scanning.
- Is this semantic, or merely decorative? Semantic.

### 28. Surface And Detail Transition Motion

Use a very subtle crossfade or instant transition for surface changes. Use a small selected-row-to-detail emphasis only when opening detail. Do not animate every row on load.

- What meaning does it communicate? Navigation or object-detail change.
- What user uncertainty does it resolve? It answers "Did the surface change or did the selected object change?"
- What state change does it reveal? Surface change, detail replacement, or row selection.
- What action does it make easier or safer? It prevents loss of context in stacked mobile layout.
- What cognitive burden does it reduce? Reorientation after navigation.
- Is this semantic, or merely decorative? Semantic if tied to state change; decorative if applied to every paint.

### 29. Health Check

Render health rows with success/danger/attention by check status, but keep Support out of primary workflow styling. Health is diagnostic and should not bleed into normal operator chrome.

- What meaning does it communicate? Infrastructure readiness.
- What user uncertainty does it resolve? It answers "Is the app behaving strangely because a dependency is down?"
- What state change does it reveal? Health check completed.
- What action does it make easier or safer? It directs support/debug action without polluting ordinary CRM workflows.
- What cognitive burden does it reduce? Diagnosing app failures.
- Is this semantic, or merely decorative? Semantic.

### 30. Auth Screen

Keep auth visually quiet. Use action-blue only on Send magic link and error red only when auth fails. Do not add brand decoration or account personalization.

- What meaning does it communicate? One focused entry action.
- What user uncertainty does it resolve? It answers "What do I need to provide to enter?"
- What state change does it reveal? Link sent, signup needed, or auth failure.
- What action does it make easier or safer? It keeps login low-friction and avoids credential confusion.
- What cognitive burden does it reduce? Entry-screen distraction.
- Is this semantic, or merely decorative? Semantic.

## Hierarchy Model

The visual hierarchy should be:

1. Current task surface and global notice, only when notice exists.
2. Current record or queue.
3. Local primary action.
4. State chips and blocking facts.
5. Secondary details and secondary actions.
6. Empty, historical, disabled, canceled, or voided data.

The current CSS often reverses this by giving separators, row borders, clusters, detail panels, and destructive confirmations the same weight. Reduce separator contrast first, then reserve stronger contrast for current state, focus, action, and risk.

## Motion Rules

- Use motion only for patch enter/exit, selected row/detail continuity, submit progress, and just-changed feedback.
- No motion should be the only signal. Pair with text, shape, color, or position.
- Respect `prefers-reduced-motion: reduce`.
- Keep motion short and causal. No decorative breathing, floating, bouncing, or looping except a minimal loading affordance.
- Use easing to imply physical continuity, not personality.

## Required Structural Corrections Before Styling

1. Add selected state to dense rows. Without this, detail styling cannot reliably show list-detail continuity.
2. Add selected state to invoice and message filters. Without this, filter styling cannot be truthful.
3. Fix or clarify the Today row action label. `Open job` currently routes into the ticket surface through `data-open-ticket`; either open the job view in Today or label it `Open ticket`.
4. Add semantic status classes or data attributes during rendering. Styling raw text like `pending` or `paid` by string matching in CSS would be brittle.
5. Add typed action variants in `actionButton()`: primary, secondary, danger, attention. The current boolean `primary` cannot express risk or reversible interruption.

## Implementation Direction For Later

When this moves from report to code, start with semantic attributes, not colors:

- `data-state="selected|loading|empty|changed"`
- `data-status="scheduled|in_progress|completed|cancelled|draft|sent|partial|paid|void|pending|failed|sent"`
- `data-action-variant="primary|secondary|attention|danger"`
- `aria-current` for active nav and selected queue rows where appropriate.
- `aria-pressed` or `aria-current` for filters, depending on whether the control is modeled as a toggle or current view selector.

Then bind CSS tokens to those attributes.

Do not start by choosing a palette and searching for places to apply it. That is backwards and would become decoration.

