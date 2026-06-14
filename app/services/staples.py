STAPLES = {
    "salt", "kosher salt", "sea salt", "table salt",
    "pepper", "black pepper", "white pepper", "red pepper flakes", "cayenne",
    "oil", "olive oil", "vegetable oil", "canola oil", "coconut oil", "cooking oil",
    "cooking spray", "nonstick spray", "pam",
    "water", "ice",
    "sugar", "white sugar",
    "baking soda", "baking powder",
}

_STAPLE_WORDS = {word for phrase in STAPLES for word in phrase.split()}
_STAPLE_PHRASES = STAPLES


def is_staple(ingredient_text: str) -> bool:
    text = ingredient_text.lower()
    if any(phrase in text for phrase in _STAPLE_PHRASES):
        return True
    words = set(text.split())
    # single-word staples (oil, salt, pepper, water, sugar) matched anywhere
    single_word_staples = {"oil", "salt", "pepper", "water", "sugar"}
    return bool(words & single_word_staples)


def filter_ingredients(ingredients: list) -> list[str]:
    result = []
    for ing in ingredients:
        if isinstance(ing, dict):
            text = ing.get("display") or ing.get("note") or ing.get("food") or ""
            if ing.get("quantity") and ing.get("unit"):
                text = f"{ing['quantity']} {ing['unit']} {text}".strip()
        else:
            text = str(ing)

        if text and not is_staple(text):
            result.append(text)
    return result
