# browser-use internals: safe monkey-patching and the mid-flight LLM swap

## What this is about
`browser-use` drives a headed browser with an LLM in a step loop. Out of the box, the LLM is fixed at `Agent` construction time. For most runs that's fine. But:
- The "boring" early part of a flow (warmup navigation, inventory browsing, building session entropy) does not need a top-tier model.
- The "high-stakes" finalize (the final click that goes through Cloudflare Turnstile; extracting the offer number) benefits from the strongest available reasoning.

Running Opus for the whole flow wastes ~80% of the tokens on trivial clicks. This skill is the canonical pattern for swapping the LLM mid-flight without forking browser-use.

## Where the LLM handle actually lives
Verified against `browser_use/agent/service.py` in the `car-offers/llm-nav/.venv` (the line numbers below may drift across browser-use versions — the shape won't):

- `Agent.__init__` stores the LLM at `self.llm` (around line 368) and keeps `self._original_llm` / `self._fallback_llm` alongside.
- Every step's model call is `response = await self.llm.ainvoke(input_messages, **kwargs)` (around line 1940 inside `get_model_output`). The attribute is read dynamically — there is no cached bound method.
- Token accounting goes through `self.token_cost_service.register_llm(<llm>)`; browser-use itself re-registers when it swaps to a fallback LLM (around line 2003–2007).
- API-key verification caches on the LLM via a `_verified_api_keys` attribute (around line 3918).
- The system prompt is built ONCE at construction (around line 509) and captures `model_name=self.llm.model` plus an `is_anthropic` flag. These are only used for initial prompt shape.

**Practical consequence:** a plain `self.llm = new_llm` is enough to reroute all subsequent reasoning calls, **provided the new model comes from the same provider family** (so the initial system prompt's provider-specific hints remain correct). Crossing providers mid-flight (Anthropic ↔ OpenAI ↔ Gemini) is out of scope for this pattern — you'd also need to rebuild the MessageManager.

No other derived objects hold a permanent reference to the original LLM that matters for the swap. `compaction_llm` and `page_extraction_llm` fall back to `self.llm` dynamically (line ~1156).

## Monkey-patch, don't fork
`browser-use` is pinned via pyproject/requirements. Do NOT fork the repo to add a method. Install a tiny additive method on the class at harness startup:

```python
from browser_use import Agent

def _ensure_mid_flight_swap_supported():
    if getattr(Agent, '_midflight_swap_patched', False):
        return

    def set_llm(self, new_llm):
        self.llm = new_llm
        setattr(new_llm, '_verified_api_keys', True)  # skip re-verification
        try:
            self.token_cost_service.register_llm(new_llm)
        except Exception:
            pass

    Agent.set_llm = set_llm
    Agent._midflight_swap_patched = True

_ensure_mid_flight_swap_supported()
```

Rules:
- Idempotent — guard with a class-level flag so the patch is safe on re-import.
- Additive — never override existing methods, never touch `self.llm` behavior outside the new helper.
- Mirror browser-use's own conventions. `set_llm` mirrors the library's fallback path (`self.llm = self._fallback_llm`; `self.token_cost_service.register_llm(...)`) exactly. If browser-use changes that path, the grep "`self.token_cost_service.register_llm`" will surface it.

## The callback API

`Agent(register_new_step_callback=fn)` accepts either a sync or async function. It is called **after** each completed step with:

```
fn(browser_state_summary, model_output, n_steps)
```

- `n_steps` is 1-indexed — it's the step that just finished.
- The callback runs inside `_handle_post_llm_processing` (around line 1697). Any exceptions there crash the run, so guard your swap logic in try/except.
- `browser_state_summary` is a `BrowserStateSummary` object; `model_output` is the `AgentOutput` pydantic model. Usually you only need `n_steps`.

## The canonical mid-flight-swap wiring

```python
early_llm = ChatAnthropic(model='claude-sonnet-4-5-20250929', ...)
late_llm  = ChatAnthropic(model='claude-opus-4-6-...', ...)

swap_state = {'done': False}

async def _maybe_swap_llm(_state, _out, n_steps):
    if swap_state['done']:
        return
    if n_steps >= SWITCH_AT:
        try:
            agent.set_llm(late_llm)
            swap_state['done'] = True
        except Exception as e:
            print(f'[swap] failed: {type(e).__name__}: {e}', flush=True)

agent = Agent(
    task=...,
    llm=early_llm,
    register_new_step_callback=_maybe_swap_llm,
    ...
)
```

The `swap_state` dict is a closure-safe latch so the callback only swaps once even if your threshold check is loose.

## Offline verification before you ship
Always verify the swap without a browser. The canonical test:
1. Build a `FakeAgent` with a `token_cost_service` stub and two `DummyLLM`s that raise `RuntimeError(self.name)` on `ainvoke`.
2. Bind the patched `set_llm` via `MethodType(Agent.set_llm, fake)`.
3. `await fake.llm.ainvoke([...])` — should raise with the early LLM's name.
4. `fake.set_llm(late)`.
5. `await fake.llm.ainvoke([...])` — should raise with the late LLM's name.

Working example: `/root/dryrun/midflight_swap_dryrun.py` used to validate the car-offers implementation.

## Gotchas
- **Script-path shadowing.** Run dry-runs from a directory YOU control, not `/tmp/`. See `SKILLS/python-script-path-hygiene.md`.
- **Providers must match.** Anthropic → Anthropic is safe. Anthropic → OpenAI is NOT — the initial system prompt has an `is_anthropic` branch that stays stuck on the original value.
- **Don't forget token accounting.** Without `token_cost_service.register_llm(new)`, usage tracking will mis-attribute calls to the early model.
- **Don't swap inside a retry loop.** The callback fires once per completed step, after retries, so you won't double-swap.
- **Version drift.** The line numbers quoted above are from browser-use as vendored in `car-offers/llm-nav/.venv` at the time of writing. If browser-use is upgraded, re-grep for `self.llm.ainvoke`, `token_cost_service.register_llm`, and `register_new_step_callback` before trusting this skill.

## Canonical example in the repo
`car-offers/llm-nav/run_site.py` — search for `_ensure_mid_flight_swap_supported` and `_maybe_swap_llm`. CLI flags: `--model-early`, `--model-late`, `--llm-switch-at-step`.
