"""Local vision backend — a small VLM served by Ollama on localhost.

Lineage: NaviGatr (the owner's ENEE408 capstone) proved the local-first
vision pattern on Pi-class hardware — small quantized models on-device
(int8 TFLite on a Coral EdgeTPU), with anything too heavy offloaded over
HTTP (monocular depth ran on an EC2 GPU API). NaviGatr never ran a
language VLM — its "descriptions" were template sentences over detector
output — so the describer model here is new; the inherited part is the
split: try the small local model first, fall back to the network. See
docs/navigatr-vlm-notes.md for the archaeology.

Zero new dependencies: this talks to Ollama's localhost HTTP API with
httpx (already required via the Anthropic SDK). Everything is lazy — no
env read, no httpx import, no connection attempt until
describe_images_local() is actually called — so QUINTACLE_VISION=cloud
(the default) never pays any of this.
"""

from .ollama import describe_images_local

__all__ = ["describe_images_local"]
