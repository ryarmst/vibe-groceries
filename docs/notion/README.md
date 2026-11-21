# Creating the Suggested Meals database (CSV import)

1. In Notion, open the page that should hold it (next to Cooking) → **⋯** → **Import** → **CSV** → choose
   `suggested-meals-import.csv`. Rename the new database **Suggested Meals**.
2. Notion imports every column as text. Change these column types (click the column name → **Edit property** →
   **Type**); the example rows make Notion create the right options:

   | Column | Change type to | Then |
   |---|---|---|
   | Status | **Status** | Arrange the groups: To-do = Suggested · In progress = Planned · Complete = Cooked, Promoted, Rejected, Skipped. Delete Notion's defaults (Not started / In progress / Done) |
   | Week, Cook By | **Date** | |
   | Course | **Select** | Add any other Cooking courses you use (Soup, Sauce/Condiment, Dessert…) |
   | Tags | **Multi-select** | |
   | Effort | **Select** | Easy, Moderate, Gourmet (same as Cooking) |
   | Servings | **Number** | |
   | Grocery Run | **URL** | |
   | Source | **Select** | Weekly Plan, Chat, Human |
   | Promote | **Checkbox** | |
   | Cuisine, Main Ingredient, Shopping Ingredients, Feedback | keep **Text** | |

3. Add the three relations, which CSV can't create (**+** → **Relation**):
   - **Uses Up** → Kitchen Pantry and Storage
   - **Based On** → Cooking
   - **Promoted To** → Cooking

   One-way relations are fine; you don't need to show them on the other database.
4. Delete the nine `EXAMPLE … (delete me)` rows. The options stay.
5. **⋯** → **Connections** → add the **vibe-groceries** connection.
6. Copy the data source ID (**⋯** → **Manage data sources** → **⋯** → **Copy data source ID**, or the
   database link) into the extension: **Settings → Notion → Suggested Meals → Save**. Then open the **Meals**
   tab: an empty week means it's connected.

Names must match exactly. Extra columns of your own are fine; a missing or renamed one is simply left empty.
