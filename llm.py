"""OpenAI-compatible LLM client with multi-provider fallback.

Configure any number of free/paid providers in .env as numbered triples:

    LLM1_BASE_URL=https://integrate.api.nvidia.com/v1
    LLM1_KEY=nvapi-...
    LLM1_MODEL=minimaxai/minimax-m3

    LLM2_BASE_URL=...
    LLM2_KEY=...
    LLM2_MODEL=...

chat() tries them in order and falls through to the next on any error
(rate limit, outage, empty reply), so hitting one provider's limit just rolls
to the next. Raises only if every provider fails.
"""
import logging
import os

log = logging.getLogger("xbot.llm")


def _truthy(v: str | None) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def providers() -> list[dict]:
    provs = []
    i = 1
    while True:
        base = os.getenv(f"LLM{i}_BASE_URL")
        key = os.getenv(f"LLM{i}_KEY")
        model = os.getenv(f"LLM{i}_MODEL")
        if not (base and key and model):
            break
        provs.append({
            "base": base, "key": key, "model": model,
            # set LLM{i}_NO_THINKING=1 for reasoning models to suppress the
            # <think> stream (cleaner JSON, faster). Safe to leave unset.
            "no_thinking": _truthy(os.getenv(f"LLM{i}_NO_THINKING")),
        })
        i += 1
    return provs


def chat(system: str, user: str, max_tokens: int = 2000,
         temperature: float = 0.7, timeout: float = 240) -> str:
    """Return the assistant text, trying each configured provider in turn."""
    from openai import OpenAI

    provs = providers()
    if not provs:
        raise RuntimeError(
            "No LLM providers configured. Set LLM1_BASE_URL / LLM1_KEY / LLM1_MODEL "
            "(and LLM2_*, ... for fallbacks) in .env.")

    last_err: Exception | None = None
    for p in provs:
        base, key, model = p["base"], p["key"], p["model"]
        try:
            client = OpenAI(base_url=base, api_key=key, timeout=timeout, max_retries=1)
            kwargs: dict = dict(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if p["no_thinking"]:
                kwargs["extra_body"] = {"chat_template_kwargs": {"thinking": False}}
            resp = client.chat.completions.create(**kwargs)
            content = (resp.choices[0].message.content or "").strip()
            if content:
                log.info("llm ok via %s (%s)", base, model)
                return content
            last_err = RuntimeError("empty response")
            log.warning("empty response from %s (%s)", base, model)
        except Exception as e:  # noqa: BLE001 - fall through to next provider
            last_err = e
            log.warning("provider %s (%s) failed: %s", base, model, e)
    raise last_err  # type: ignore[misc]
