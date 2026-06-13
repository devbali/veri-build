"""Lint — Hook 1: Interface-only verification.

Reads a .veri.md, parses Veri DSL blocks, generates .fst,
and runs fstar.exe on the interface WITHOUT --admit_smt_queries.
This checks that types, signatures, and pre/post-conditions
are well-formed F* — without any implementations."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from .spec import read_spec, generate_interface, ExtractedSpec


def _get_veri_dsl_version() -> str:
    """Read the current Veri DSL version from the VERSION file."""
    version_path = Path(__file__).resolve().parent / 'dsl' / 'src' / 'VERSION'
    if version_path.exists():
        return version_path.read_text().strip()
    return 'unknown'


def _major_minor(version: str) -> str:
    """Extract 'major.minor' from a semver string (e.g. '0.0.1' → '0.0')."""
    parts = version.split('.')
    return f'{parts[0]}.{parts[1]}' if len(parts) >= 2 else version


class LintError(Exception):
    """Interface verification failed with F* errors."""

    def __init__(self, message: str, fstar_stderr: str = ""):
        self.message = message
        self.fstar_stderr = fstar_stderr
        super().__init__(message)


def find_fstar() -> Optional[str]:
    """Locate fstar.exe on the system."""
    path = shutil.which("fstar.exe")
    if path:
        return path
    # Common alternative locations
    candidates = [
        "~/tools/fstar/fstar/bin/fstar.exe",
        "/usr/local/bin/fstar.exe",
        "/opt/fstar/bin/fstar.exe",
    ]
    for c in candidates:
        p = Path(c).expanduser()
        if p.exists():
            return str(p)
    return None


def find_krml() -> Optional[str]:
    """Locate krml binary."""
    path = shutil.which("krml")
    if path:
        return path
    fstar_dir = Path(find_fstar() or "").parent
    krml_candidate = fstar_dir / "krml"
    if krml_candidate.exists():
        return str(krml_candidate)
    return None


def lint_interface(
    md_path: Path,
    module_name: Optional[str] = None,
    fstar_bin: Optional[str] = None,
    rlimit: int = 5,
    fuel: int = 2,
) -> ExtractedSpec:
    """Parse .veri.md and verify the F* interface.

    This is Hook 1: no LLM, no admits, no stubs.
    Checks that types, val signatures, and pre/post-conditions
    are valid F*.

    Args:
        md_path: Path to .veri.md file
        module_name: Override module name
        fstar_bin: Path to fstar.exe (auto-detect if None)
        rlimit: Z3 resource limit (default 5)
        fuel: SMT fuel (default 2)

    Returns:
        Parsed ExtractedSpec (if interface is sound)

    Raises:
        LintError: If F* interface verification fails or version mismatch
        SyntaxError: If Veri DSL parsing fails
    """
    spec = read_spec(md_path, module_name)

    # ── Version check (required, major.minor only) ──
    if not spec.veri_version:
        raise LintError(
            "No VERI_VERSION declared. Add to the first Veri DSL block: "
            f"VERI_VERSION {_get_veri_dsl_version()}"
        )
    dsl_version = _get_veri_dsl_version()
    if _major_minor(spec.veri_version) != _major_minor(dsl_version):
        raise LintError(
            f"VERI_VERSION mismatch: spec says {spec.veri_version}, "
            f"DSL is {dsl_version}. Upgrade Veri DSL toolchain for "
            f"major.minor {_major_minor(spec.veri_version)} support, or "
            f"update VERI_VERSION in your .veri.md to {dsl_version}."
        )

    fsti_code = generate_interface(spec)

    fstar = fstar_bin or find_fstar()
    if not fstar:
        raise RuntimeError(
            "fstar.exe not found. Install F* or set --fstar-bin."
        )

    with tempfile.TemporaryDirectory(prefix="veri-lint-") as tmp:
        fsti_path = Path(tmp) / f"{spec.module_name}.fst"
        fsti_path.write_text(fsti_code)

        cmd = [
            fstar,
            "--z3rlimit", str(rlimit),
            "--fuel", str(fuel),
            "--ifuel", str(fuel),
            str(fsti_path),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            error_lines = _format_fstar_errors(result.stderr, result.stdout)
            raise LintError(
                f"Interface check failed for {spec.module_name}:\n"
                + "\n".join(error_lines),
                fstar_stderr=result.stderr,
            )

    return spec


def lint_with_stubs(
    md_path: Path,
    module_name: Optional[str] = None,
    fstar_bin: Optional[str] = None,
    rlimit: int = 50,
    fuel: int = 8,
) -> ExtractedSpec:
    """Parse .veri.md and run F* with admits (structural check).

    Used after filling TODOs to check the full file before extraction.
    Higher default rlimit since we're checking actual implementations.

    Args:
        md_path: Path to .veri.md (with TODOs filled)
        module_name: Override module name
        fstar_bin: Path to fstar.exe
        rlimit: Z3 resource limit (default 50 for full verification)
        fuel: SMT fuel (default 8)

    Returns:
        Parsed ExtractedSpec

    Raises:
        LintError: If verification fails
    """
    from .spec import read_spec, generate_fst_with_stubs

    spec = read_spec(md_path, module_name)
    fst_code = generate_fst_with_stubs(spec)

    fstar = fstar_bin or find_fstar()
    if not fstar:
        raise RuntimeError("fstar.exe not found.")

    with tempfile.TemporaryDirectory(prefix="veri-build-") as tmp:
        fst_path = Path(tmp) / f"{spec.module_name}.fst"
        fst_path.write_text(fst_code)

        cmd = [
            fstar,
            "--admit_smt_queries", "true",
            "--z3rlimit", str(rlimit),
            "--fuel", str(fuel),
            "--ifuel", str(fuel),
            str(fst_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            error_lines = _format_fstar_errors(result.stderr, result.stdout)
            raise LintError(
                f"Verification failed for {spec.module_name}:\n"
                + "\n".join(error_lines),
                fstar_stderr=result.stderr,
            )

    return spec


def _format_fstar_errors(stderr: str, stdout: str) -> list:
    """Extract and format F* error messages."""
    lines = []
    for line in (stderr + stdout).split('\n'):
        line = line.strip()
        if not line:
            continue
        # F* errors look like: "file.fst(12,5-13,8): Error 19: Subtyping check failed"
        if 'Error' in line or 'error' in line:
            lines.append(f"  ❌ {line}")
    if not lines:
        lines.append(f"  ❌ (see stderr for details)")
    return lines


def auto_tune_rlimit(
    md_path: Path,
    module_name: Optional[str] = None,
    fstar_bin: Optional[str] = None,
    max_rlimit: int = 500,
) -> int:
    """Binary search for the minimum rlimit that passes interface check."""
    lo, hi = 5, max_rlimit
    best = None

    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            lint_interface(md_path, module_name, fstar_bin, rlimit=mid)
            best = mid
            hi = mid - 1
        except LintError:
            lo = mid + 1

    return best or max_rlimit
