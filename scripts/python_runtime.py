"""
python_runtime.py — Runtime contract enforcement for Veri DSL Python-assert backend.

Designed to go *directly on real implementation functions* via @contract:

    from python_runtime import contract, PreconditionError, PostconditionError
    from my_spec_conditions import add_element__requires, add_element__ensures

    @contract(requires=add_element__requires, ensures=add_element__ensures)
    def add_element(existing, new_elem):
        # real implementation here
        ...

Behavior is controlled by the CONTRACT_ASSERT_ENABLED env var (or ContractSettings):
  - Enabled (default when var is set): evaluates requires/ensures, raises AssertionError
  - Disabled (default otherwise): no-op pass-through, zero runtime overhead

Use case: libraries enable assertions during fuzz testing / CI, disable in production.
"""

import functools
import os as _os


# ── Global toggle ───────────────────────────────────────────────────────

class ContractSettings:
    """Global-toggle for contract assertion behavior.

    Priority:
      1. Programmatic override: ContractSettings.enable() / .disable()
      2. CONTRACT_ASSERT_ENABLED env var (``1`` / ``true`` / ``yes``)
      3. Default: disabled (no assertions at runtime)
    """
    _enabled: bool | None = None

    @classmethod
    @property
    def enabled(cls) -> bool:
        if cls._enabled is None:
            raw = _os.environ.get("CONTRACT_ASSERT_ENABLED", "").strip().lower()
            cls._enabled = raw in ("1", "true", "yes")
        return cls._enabled

    @classmethod
    def enable(cls):
        """Programmatically enable contract assertions."""
        cls._enabled = True

    @classmethod
    def disable(cls):
        """Programmatically disable contract assertions."""
        cls._enabled = False

    @classmethod
    def reset(cls):
        """Reset to env-var detection on next access."""
        cls._enabled = None


# ── Error types ─────────────────────────────────────────────────────────

class PreconditionError(AssertionError):
    """Raised when a @contract's precondition is violated (assert mode only)."""
    def __init__(self, func_name: str, detail: str = ""):
        msg = f"[Veri DSL Contract] Precondition failed: {func_name}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


class PostconditionError(AssertionError):
    """Raised when a @contract's postcondition is violated (assert mode only)."""
    def __init__(self, func_name: str, detail: str = ""):
        msg = f"[Veri DSL Contract] Postcondition failed: {func_name}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


class ContractDryRun(AssertionError):
    """Raised instead of calling the real function in DRY_RUN verification mode.

    When CONTRACT_DRY_RUN=1 is set, the decorator evaluates requires/ensures,
    then raises ContractDryRun instead of invoking the wrapped function.
    This allows verification without having the real implementation available
    (used by the verify CLI).
    """
    def __init__(self, func_name: str):
        super().__init__(f"[Veri DSL Contract Dry-Run] {func_name} — conditions evaluated (function not called)")


# ── The @contract decorator ─────────────────────────────────────────────

def _is_dry_run() -> bool:
    return _os.environ.get("CONTRACT_DRY_RUN", "").strip().lower() in ("1", "true", "yes")


def contract(*, requires=None, ensures=None):
    """Decorator that enforces pre/post conditions on the *real* implementation.

    Two modes, controlled independently:

    **Assert mode** (CONTRACT_ASSERT_ENABLED=1):
      - Evaluates requires(args) BEFORE the function call
      - Raises PreconditionError if False
      - Calls the real function
      - Evaluates ensures(result, *args) AFTER the call
      - Raises PostconditionError if False

    **Pass-through mode** (default, or CONTRACT_ASSERT_ENABLED=0):
      - Zero overhead: calls the real function directly, no evaluation

    **Dry-run mode** (CONTRACT_DRY_RUN=1, independent of assert toggle):
      - Evaluates requires/ensures but does NOT call the real function
      - Raises ContractDryRun after evaluating conditions
      - Used by the Veri DSL verify CLI to check contract correctness

    Args:
        requires: Callable(*args, **kwargs) -> bool. Precondition predicate.
        ensures:  Callable(result, *args, **kwargs) -> bool. Postcondition predicate.

    Raises:
        PreconditionError  — assert mode, requires returned False
        PostconditionError — assert mode, ensures returned False
        ContractDryRun     — dry-run mode (CI verification)
    """
    def decorator(func):
        # No conditions at all — pure pass-through
        if requires is None and ensures is None:
            return func

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # ── Dry-run mode: check conditions, skip the call ──
            if _is_dry_run():
                if requires is not None:
                    requires(*args, **kwargs)
                raise ContractDryRun(func.__name__)

            # ── Assert mode vs pass-through ──
            if not ContractSettings.enabled:
                return func(*args, **kwargs)

            # ✔ Assert mode — enforce pre/post
            if requires is not None:
                if not requires(*args, **kwargs):
                    raise PreconditionError(
                        func.__name__,
                        f"requires({_format_call(func, args, kwargs)}) returned False",
                    )

            result = func(*args, **kwargs)

            if ensures is not None:
                if not ensures(result, *args, **kwargs):
                    raise PostconditionError(
                        func.__name__,
                        f"ensures({_format_result(result)}, {_format_call(func, args, kwargs)}) returned False",
                    )
            return result

        # Tag the wrapper for verification tooling
        wrapper.__wrapped__ = func
        wrapper.__contract_requires__ = requires
        wrapper.__contract_ensures__ = ensures

        return wrapper
    return decorator


# ── Helpers ─────────────────────────────────────────────────────────────

def _format_call(func, args, kwargs) -> str:
    """Format function call args for error messages."""
    import inspect
    sig = inspect.signature(func)
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()
    parts = [f"{name}={repr(val)}" for name, val in bound.arguments.items()]
    return ", ".join(parts)


def _format_result(result) -> str:
    """Format return value for error messages."""
    return repr(result)
