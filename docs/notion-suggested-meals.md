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

| Property | Type | Written by | Purpose |
|---|---|---|---|
| `Name` | title | agent | Dish name, Cooking style (no type prefix) |
| `Status` | status | both | Lifecycle (below) |
| `Week` | date | agent | Plan week start (Thursday, flyer day) |
| `Cook By` | date | agent | Latest good day to cook: earliest of key perishable expiry and freshness. Orders the week |
| `Course` | select | agent | Same options as Cooking (e.g. Main, Side, Soup, Salad, Breakfast…) |
| `Cuisine` | text | agent | Comma-separated, as in Cooking |
| `Main Ingredient` | text | agent | Single value, as in Cooking (e.g. "Pork Shoulder") |
| `Tags` | multi-select | agent | Cooking's vocabulary (Bulk, Braise, Pressure Cooker, Sous Vide…) **plus** Quick, Sheet Pan, One Pot, Freezer-Friendly, New |
| `Novelty` | select | agent | Regular · Twist (variation on a known dish) · New. Drives the "mostly proven, some new" balance |
| `Servings` | number | agent | Default 4–6; Bulk meals more |
| `Active Time` | number (min) | agent | Hands-on minutes: the effort signal |
| `Total Time` | number (min) | agent | Including braise or rest time |
| `Est. Cost` | number ($) | agent | Priced from the catalogue at plan time |
| `Cost / Serving` | formula | — | `Est. Cost / Servings` |
| `Deals` | text | agent | e.g. "Pork picnic $6.61/kg (ends Nov 25); Sweet potato 45% off" |
| `Uses Up` | relation → Pantry | agent | On-hand items (especially near `Expiration`) this meal consumes: the waste signal |
| `Shopping Ingredients` | text | agent | Same manifest format as Cooking (`Serves: 6` then `Name \| qty[\| optional]`); copied on promotion |
| `Based On` | relation → Cooking | agent | When it's a regular or a twist on an existing recipe |
| `Grocery Run` | url | agent | Link to the run that bought its ingredients |
| `Source` | select | agent | Weekly Plan · Chat · Human |
| `Cooked On` | date | human (or check-in) | Set when cooked |
| `Rating` | select | human | ★ to ★★★★★ |
| `Leftovers` | select | human | None · Some (planned) · Too much · Not enough: portion learning |
| `Feedback` | text | human | In your own words: why rejected, what to change ("less salt", "kids loved it", "too fiddly for a weeknight") |
| `Promote` | checkbox | human | "Save this to Cooking" request; the agent processes it |
| `Promoted To` | relation → Cooking | agent | Set after promotion |
| `Suggested By` | created by / text | — | Which device or person (if you want attribution) |

**Optional, on Groceries** (one new relation, so a rejected meal's unique ingredients can be skipped
before they're bought): `For Meals` (relation → Suggested Meals, two-way).

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
- **Hall of Fame**: Rating ≥ ★★★★, not yet promoted.

## How the agent uses it
- **Planning:**
  - Avoid repeating anything cooked in the last ~3 weeks unless it was rated ★★★★+.
  - Avoid anything rejected with negative Feedback.
  - Keep the Novelty mix at about 70% Regular or Twist and about 30% New.
  - Every Planned meal must have a Cook By and every perishable it buys must belong to a meal.
- **Learning signals:**
  - Ratings and Feedback adjust cuisine, protein and effort preferences.
  - Leftovers adjust servings.
  - Skipped meals reduce effort and the meal count for the following week.
- **Waste:** "Uses Up" is filled from pantry rows whose `Expiration` falls within the week. Meals with
  Uses Up are scheduled first.
