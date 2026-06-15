def score_recipe(recipe: dict, sale_items: list[dict]) -> tuple[int, list[str]]:
    """
    Score a recipe by how many sale items appear in its ingredients.
    Returns (score, matched_sale_item_names).
    """
    sale_names = {item["name"].lower() for item in sale_items}
    ingredients = recipe.get("recipeIngredient", [])

    matched = []
    for ing in ingredients:
        food = ""
        if isinstance(ing, dict):
            food_field = ing.get("food")
            if isinstance(food_field, dict):
                food_field = food_field.get("name", "")
            food = (food_field or ing.get("note") or ing.get("display") or "").lower()
        elif isinstance(ing, str):
            food = ing.lower()

        for sale in sale_names:
            sale_words = set(sale.split())
            if any(word in food for word in sale_words if len(word) > 3):
                matched.append(sale)
                break

    return len(matched), list(set(matched))


def rank_existing_recipes(
    recipes: list[dict], sale_items: list[dict], top_n: int = 5
) -> list[dict]:
    scored = []
    for recipe in recipes:
        score, matches = score_recipe(recipe, sale_items)
        if score > 0:
            scored.append({**recipe, "_score": score, "_matched_sales": matches})
    scored.sort(key=lambda r: r["_score"], reverse=True)
    return scored[:top_n]
