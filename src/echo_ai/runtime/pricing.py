"""Prefer provider-reported USD; otherwise estimate with LiteLLM's bundled rates."""

import math
import os


def format_cost(amount, *, estimated=False):
    return f"{'~' if estimated else ''}${amount:.2f} USD"


def cost_usage(config, usage):
    if config.provider == "hosted_vllm":
        return {"cost_usd": 0.0, "cost_source": "local"}
    if config.provider == "xai":
        ticks = usage.get("cost_in_usd_ticks")
        if type(ticks) is int and ticks >= 0:
            return {"cost_usd": ticks / 10_000_000_000, "cost_source": "reported"}
        reported = usage.get("cost")
        if type(reported) in (int, float) and math.isfinite(reported) and reported >= 0:
            return {"cost_usd": reported, "cost_source": "reported"}
    if "prompt_tokens" in usage and "completion_tokens" in usage:
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        from litellm import cost_per_token
        from litellm.types.utils import Usage

        try:
            costs = cost_per_token(
                model=f"{config.provider}/{config.model}",
                custom_llm_provider=config.provider, usage_object=Usage(**usage),
            )
            total = sum(costs)
            if math.isfinite(total) and total >= 0:
                return {"cost_usd": total, "cost_source": "estimated"}
        except Exception:  # noqa: BLE001 - SDK pricing failures must not fail model calls
            # Unknown model/pricing must not discard a usable model response.
            return {"cost_usd": None, "cost_source": "unknown"}
    return {"cost_usd": None, "cost_source": "unknown"}
