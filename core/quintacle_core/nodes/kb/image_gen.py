from __future__ import annotations

import base64

from openai import OpenAI

# The one deliberate exception to "everything goes through the anthropic
# client" elsewhere in this app — Anthropic has no image generation model at
# all, so this is a genuinely separate provider. Reads OPENAI_API_KEY from
# the environment (same .env file ANTHROPIC_API_KEY already lives in,
# loaded once at startup by api.py's load_dotenv()).
# The mini model + explicit low quality — cheapest combination available;
# "auto" quality on the full model defaults toward pricier tiers.
_MODEL = "gpt-image-1-mini"
_QUALITY = "low"


def generate_image(prompt: str) -> bytes:
    client = OpenAI()
    response = client.images.generate(model=_MODEL, prompt=prompt, size="1024x1024", quality=_QUALITY)
    return base64.b64decode(response.data[0].b64_json)
