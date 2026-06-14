import base64
import json
from pathlib import Path

import anthropic

from app.config import settings

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _encode_image(image_bytes: bytes, media_type: str) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
        },
    }


def extract_sale_items(images: list[tuple[bytes, str]]) -> list[dict]:
    """
    images: list of (image_bytes, media_type) tuples
    Returns list of dicts: {name, price, unit, category}
    """
    content = []
    for image_bytes, media_type in images:
        content.append(_encode_image(image_bytes, media_type))

    content.append({
        "type": "text",
        "text": (
            "These are pages from a grocery store weekly ad circular. "
            "Extract every sale item you can find. "
            "Return a JSON array where each element has these fields: "
            "name (string), price (string, e.g. '$2.99' or '2/$5'), "
            "unit (string, e.g. 'lb', 'each', 'oz', or empty string if not specified), "
            "category (string, one of: produce, meat, seafood, dairy, deli, bakery, "
            "frozen, pantry, beverages, snacks, other). "
            "Return ONLY the JSON array, no other text."
        ),
    })

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
