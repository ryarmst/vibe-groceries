# Notion: Suggested Meals database (proposal)

The staging ground for meals the agent proposes. It replaces the Kitchen artifact's `recipes` collection.
People keep, cook, rate, reject or promote meals here or from the extension. The agent reads the outcomes
to plan better next time.

**Design rules**
- Mirror **Cooking's** fields (`Course`, `Cuisine`, `Main Ingredient`, `Tags`, `Shopping Ingredients`,
  page format) so promotion is a copy, not a translation.
- Every property earns its place by serving one of: deals, effort, waste, or learning.
- Agent-written fields and human-written fields are kept apart, so neither overwrites the other.

## Properties

Simplified (2026-11-21): details like the deals used, active/total time and cost per serving live in the page's
📌 summary line instead of separate fields; how it went goes in Feedback. Import steps: [notion/README.md](notion/README.md).

| Property | Type | Written by | Purpose |
|---|---|---|---|
| `Name` | title | agent | Dish name, Cooking style |
| `Status` | status | both | Suggested → Planned → Cooked / Promoted; or Rejected / Skipped |
| `Week` | date | agent | Plan week start (Thursday, flyer day) |
| `Cook By` | date | agent | Latest good day to cook (perishables); orders the week |
| `Course` | select | agent | Same options as Cooking |
| `Cuisine` | text | agent | As in Cooking |
| `Main Ingredient` | text | agent | As in Cooking |
| `Tags` | multi-select | agent | Cooking's tags plus Quick, Sheet Pan, One Pot, Freezer-Friendly, New |
| `Effort` | select | agent | Easy · Moderate · Gourmet (as in Cooking) |
| `Servings` | number | agent | Default 4–6 |
| `Uses Up` | relation → Pantry | agent | On-hand items it uses before they expire |
| `Shopping Ingredients` | text | agent | Cooking's manifest format; copied on promotion |
| `Based On` | relation → Cooking | agent | A regular or the recipe it's a twist on |
| `Grocery Run` | url | agent | The run that bought its ingredients |
| `Source` | select | agent | Weekly Plan · Chat · Human |
| `Feedback` | text | people | In your own words, with who and when |
| `Promote` | checkbox | people | "Save this to Cooking" |
| `Promoted To` | relation → Cooking | agent | Set after promotion |

## Status lifecycle

```
            ┌──────── Rejected   (human; Feedback says why)
Suggested ──┤
 (to-do)    └──▶ Planned ──▶ Cooked ──▶ (Promote ✓) ──▶ Promoted
                (in progress)   │
                                └──▶ Skipped (auto, 3+ days past Cook By, or human "didn't get to it")
```

Notion status groups:
- To-do: *Suggested*
- In progress: *Planned*
- Complete: *Cooked*, *Promoted*, *Rejected*, *Skipped*

| Transition | Who | Side effects (agent) |
|---|---|---|
| Suggested → Planned | human (Keep) | Its ingredients stay in the run / Groceries |
| Suggested → Rejected | human | Offer to drop its unique ingredients from the pending run and Groceries; learn from Feedback |
| Planned → Cooked | human / check-in | Propose pantry updates (used-up items cleared, leftovers row with expiry): Confirm tier |
| Cooked + Promote | human ticks | Create the Cooking page (saved-page format) with fields copied; set `Promoted To`; Status → Promoted; offer `Regular Recipe?` (question 5) |
| Planned → Skipped | auto / human | Ask what happened to its perishables (frozen? still good? tossed?) and update the pantry; lowers similar suggestions |

## Page body (agent-written; same shape as a saved Cooking page)
1. 📌 grey callout: why this week (deals, uses-up, Cook By), active/total time, servings, cost/serving.
2. **Ingredients**: imperial and metric; on-hand items marked "(on hand)".
3. **Process**: numbered, bold stage labels, bold times and temperatures; "freeze on arrival" notes for
   late-week proteins.
4. **Leftovers & storage**: how it keeps, how to reheat, how to repurpose.
5. **Notes**: substitutions if a deal item is out of stock.

## Suggested views
- **This Week**: board by Status, filter Week = current, sorted by Cook By.
- **Calendar**: by Cook By.
- **To Promote**: Promote = ✓ and Promoted To is empty.
- **Learning**: Rejected and Skipped with Feedback, newest first.

## How the agent uses it
- **Planning:**
  - Avoid repeating anything cooked in the last ~3 weeks unless it was promoted.
  - Avoid anything rejected with negative Feedback.
  - Mostly proven dishes, about one new one a week (tagged New).
  - Every Planned meal must have a Cook By and every perishable it buys must belong to a meal.
- **Learning signals:**
  - Feedback (and Rejected/Promoted) adjusts cuisine, protein, effort and portion preferences.
  - Skipped meals reduce effort and the meal count for the following week.
- **Waste:** "Uses Up" is filled from pantry rows whose `Expiration` falls within the week. Meals with
  Uses Up are scheduled first.
