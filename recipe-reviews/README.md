# Recipe reviews

Reviewed overrides for UniTools World Recipes v2.0.0 (CC BY-SA 4.0, attribution
**UniTools — theunitools.com**), applied with:

```sh
aimo ingest-recipes --file /data/unitools-recipes.json \
  --expected-sha256 41fdc0572b7272ca557d2df22a0fac1cc1f18146e97ebd2c8258c395daf87d8a \
  --review-file recipe-reviews/unitools-v2.0.0.json
```

The source record stays in each new version's `original` field. Only facts with a
stated basis are set; anything that needs a cooking judgement stays unresolved.

| Recipe | Ingredient | Change | Basis |
|---|---|---|---|
| Carbonara | spaghetti | form `dry` | 100 g per serving boiled in salted water: dried-pasta portion |
| Carbonara | guanciale | form `cured` | Guanciale is cured pork cheek by definition |
| Carbonara | yolks, egg | form `raw` | Recipe separates and uses raw eggs |
| Carbonara | pecorino | form `hard cheese` | Pecorino romano is a hard cheese; source notes "finely grated" |
| Carbonara | pepper | 1 tsp → 2.3 g, form `ground` | USDA FoodData Central SR Legacy, black pepper household portion |
| Lasagne | beef, pork | form `raw minced` | Ingredient name |
| Lasagne | pancetta | form `cured` | Pancetta is cured pork belly by definition |
| Lasagne | tomatopaste | 2 tbsp → 32 g | USDA FoodData Central SR Legacy, tomato paste, 1 tbsp = 16 g |
| Lasagne | milk, bechamelmilk, wine, butter, flour, parmesan | form from name | Ingredient name |

Still unresolved (need a decision or a source, not invented here):

- Carbonara `pepper`: source scaling is `damped` with no formula.
- Carbonara `salt`: source has no quantity ("to taste").
- Lasagne `soffritto`: one 300 g line for onion, carrot and celery with no split.
- Lasagne `stock` (liquid or concentrate) and `sheets` (dry or fresh): form not stated.
- Lasagne `nutmeg`: "1 pinch", damped.

Each matched ingredient also needs reviewed product evidence
(`aimo import-recipe-product-evidence`) before a basket can be prepared.
