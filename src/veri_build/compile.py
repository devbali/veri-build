"""Compile — Extract C via KaRaMeL, compile to WASM or .so, generate wrappers.

Uses the local F* + KaRaMeL toolchain or a Docker image.

Docker image (verification-builder):
  - F* (fstar.exe)
  - KaRaMeL (krml)
  - Emscripten (emcc)
  - GCC
"""

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from .lint import find_fstar, find_krml
from .spec import read_spec


DOCKER_IMAGE = "verification-builder:latest"


def _ensure_docker_image():
    """Build the Docker image if it doesn't exist."""
    result = subprocess.run(
        ["docker", "images", "-q", DOCKER_IMAGE],
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        return  # Image exists

    # Build from Dockerfile in this package
    dockerfile_dir = Path(__file__).resolve().parent.parent.parent
    dockerfile = dockerfile_dir / "Dockerfile"

    print(f"🐳 Building Docker image {DOCKER_IMAGE}...")
    subprocess.run(
        ["docker", "build", "-t", DOCKER_IMAGE, "-f", str(dockerfile), str(dockerfile_dir)],
        check=True,
    )


def _run_in_docker(cmd: list, workdir: Path, capture: bool = True, timeout: int = 60):
    """Run a command inside the verification-builder Docker container.

    Mounts the workdir as /workspace.
    """
    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{workdir.resolve()}:/workspace",
        "-w", "/workspace",
        DOCKER_IMAGE,
    ] + cmd

    return subprocess.run(
        docker_cmd,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )


def _run_locally(cmd: list, timeout: int = 60):
    """Run a command locally."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _find_emcc() -> Optional[str]:
    """Locate emcc (Emscripten compiler)."""
    path = shutil.which("emcc")
    if path:
        return path
    candidates = [
        "~/emsdk/upstream/emscripten/emcc",
        "/opt/emsdk/upstream/emscripten/emcc",
        "/usr/lib/emscripten/emcc",
    ]
    for c in candidates:
        p = Path(c).expanduser()
        if p.exists():
            return str(p)
    return None


def extract_c(
    veri_path: Path,
    module_name: str,
    fstar_bin: Optional[str] = None,
    use_docker: bool = False,
    impl_code: str = "",
) -> Optional[Path]:
    """Extract F* to C via KaRaMeL.

    Generates a complete .fst with the spec's types, val signatures,
    AND real implementation code (instead of admit() stubs).
    Compiles to C via F* codegen + KaRaMeL.

    Args:
        veri_path: Path to .veri.md
        module_name: Module name for F* extraction
        fstar_bin: Path to fstar.exe (local only)
        use_docker: Run in Docker container
        impl_code: F* let-bindings to compile (from agent or manual fill).
                   If empty, falls back to admit() stubs.

    Returns:
        Path to generated .c file, or None on failure
    """
    # Generate complete .fst with spec + real implementations
    spec = read_spec(veri_path, module_name)
    from .spec import generate_complete_fst
    fst_code = generate_complete_fst(spec, impl_code)

    tmp = Path(tempfile.mkdtemp(prefix="veri-extract-"))
    fst_path = tmp / f"{module_name}.fst"
    fst_path.write_text(fst_code)

    try:
        if use_docker:
            _ensure_docker_image()
            # Verify
            result = _run_in_docker(
                ["fstar.exe", "--admit_smt_queries", "true", "--cache_checked_modules",
                 "--odir", "/workspace/", f"/workspace/{module_name}.fst"],
                workdir=tmp,
            )
            if result.returncode != 0:
                print(f"   F* verify failed: {result.stderr[:300]}")
                return None

            # Extract KaRaMeL IR
            result = _run_in_docker(
                ["fstar.exe", "--codegen", "krml", "--extract", module_name,
                 "--admit_smt_queries", "true", "--cache_checked_modules",
                 "--already_cached", f"Prims FStar {module_name}",
                 "--odir", "/workspace/", f"/workspace/{module_name}.fst"],
                workdir=tmp,
            )
            if result.returncode != 0:
                print(f"   KaRaMeL extraction failed: {result.stderr[:300]}")
                return None

            # Generate C
            c_dir = tmp / "c"
            c_dir.mkdir(exist_ok=True)
            result = _run_in_docker(
                ["krml", "-skip-compilation",
                 f"/workspace/{module_name}.krml",
                 "-tmpdir", "/workspace/c"],
                workdir=tmp,
            )
            if result.returncode != 0:
                print(f"   KaRaMeL C gen failed: {result.stderr[:300]}")
                return None

        else:
            # Local
            fstar = fstar_bin or find_fstar()
            krml = find_krml()
            if not fstar or not krml:
                print("   fstar.exe or krml not found. Install toolchain or use --docker.")
                return None

            # Verify
            result = _run_locally([
                fstar, "--admit_smt_queries", "true",
                "--cache_checked_modules", "--odir", str(tmp), str(fst_path),
            ])
            if result.returncode != 0:
                print(f"   F* verify failed: {result.stderr[:200]}")
                return None

            # Extract KaRaMeL IR
            krml_out = tmp / f"{module_name}.krml"
            result = _run_locally([
                fstar, "--codegen", "krml", "--extract", module_name,
                "--admit_smt_queries", "true", "--cache_checked_modules",
                "--already_cached", f"Prims FStar {module_name}",
                "--odir", str(tmp), str(fst_path),
            ])
            if result.returncode != 0 or not krml_out.exists():
                print(f"   KaRaMeL extraction failed")
                return None

            # Generate C
            c_dir = tmp / "c"
            c_dir.mkdir(exist_ok=True)
            result = _run_locally([
                krml, "-skip-compilation", str(krml_out), "-tmpdir", str(c_dir),
            ])
            if result.returncode != 0:
                print(f"   KaRaMeL C gen failed: {result.stderr[:200]}")
                return None

        # Find the generated .c file
        c_files = list(tmp.rglob("*.c"))
        for cf in c_files:
            if cf.name == f"{module_name}.c" or cf.name.startswith(module_name):
                return cf

        # Fallback: return any .c file
        if c_files:
            return c_files[0]

        return None

    finally:
        import shutil as sh
        sh.rmtree(tmp, ignore_errors=True)


def compile_wasm(
    c_path: Path,
    module_name: str,
    out_dir: Path,
    use_docker: bool = False,
) -> Optional[Path]:
    """Compile the extracted C to WASM via Emscripten.

    Args:
        c_path: Path to extracted .c file
        module_name: Module name for output file
        out_dir: Output directory
        use_docker: Run in Docker container

    Returns:
        Path to .wasm file, or None on failure
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    c_dir = c_path.parent
    wasm_path = out_dir / f"{module_name}.wasm"

    if use_docker:
        _ensure_docker_image()
        result = _run_in_docker(
            ["emcc", "-O2", "-o", f"/workspace/{module_name}.wasm",
             f"/workspace/{c_path.name}", "-s", "WASM=1",
             "-s", "SIDE_MODULE=1", "-s", "EXPORTED_FUNCTIONS=['_' + s for s in '']"],
            workdir=c_dir,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"   WASM compilation failed: {result.stderr[:300]}")
            return None
        # Copy wasm out
        import shutil
        wasm_src = c_dir / f"{module_name}.wasm"
        if wasm_src.exists():
            shutil.copy2(wasm_src, wasm_path)
            return wasm_path
        return None

    else:
        emcc = _find_emcc()
        if not emcc:
            print("   emcc not found. Install Emscripten or use --docker.")
            return None

        result = _run_locally([
            emcc, "-O2",
            "-o", str(wasm_path),
            str(c_path),
            "-s", "WASM=1",
            "-s", "SIDE_MODULE=1",
        ], timeout=120)

        if result.returncode != 0 or not wasm_path.exists():
            print(f"   WASM compilation failed: {result.stderr[:200]}")
            return None

        return wasm_path


def generate_wrappers(
    c_path: Path,
    module_name: str,
    out_dir: Path,
) -> Tuple[Optional[Path], Optional[Path]]:
    """Generate TypeScript and Python wrapper stubs.

    Reads the .h file to extract function signatures,
    generates per-function bindings.

    Args:
        c_path: Path to the .c generated by KaRaMeL
        module_name: Module name
        out_dir: Output directory

    Returns:
        (ts_path, py_path) or (None, None) if no .h found
    """
    header = c_path.with_suffix(".h")
    if not header.exists():
        # Try Prims.h in parent dir
        header = c_path.parent / "Prims.h"

    try:
        from convert import parse_c_header
        functions = []
        if header.exists():
            functions = parse_c_header(header)
    except (ImportError, Exception):
        functions = []

    ts_path = out_dir / f"{module_name}.verified.ts"
    py_path = out_dir / f"{module_name}_wrapper.py"

    _write_ts_wrapper(ts_path, module_name, functions)
    _write_py_wrapper(py_path, module_name, functions)

    return ts_path, py_path


def _write_ts_wrapper(path: Path, module_name: str, functions: list):
    """Write a TypeScript wrapper with per-function bindings."""
    lines = [
        f"// {module_name}.verified.ts — Auto-generated",
        f"// Functions: {', '.join(f.name for f in functions) if functions else 'none'}",
        "",
        "export interface VerifiedModule {",
    ]
    for fn in functions:
        params = ", ".join(f"{p[0]}: number" for p in getattr(fn, 'params', []))
        ret = "number"
        if getattr(fn, 'return_type', None) == 'bool':
            ret = "boolean"
        lines.append(f"  {fn.name}({params}): {ret};")
    lines.extend([
        "}",
        "",
        "export class VerifiedStateManager {",
        "  private module: VerifiedModule | null = null;",
        "  async initialize(wasmUrl: string): Promise<void> {",
        '    const wasm = await WebAssembly.instantiateStreaming(',
        "      fetch(wasmUrl)",
        "    );",
        "    this.module = wasm.instance.exports as unknown as VerifiedModule;",
        "  }",
        "}",
        "",
    ])
    path.write_text("\n".join(lines) + "\n")


def _write_py_wrapper(path: Path, module_name: str, functions: list):
    """Write a Python ctypes wrapper with per-function bindings."""
    lines = [
        f'"""Verified module wrapper: {module_name}. Auto-generated."""',
        "",
        "import ctypes",
        "from pathlib import Path",
        "",
        f"class {module_name}Wrapper:",
        f'    """Wrapper for the verified {module_name} C library."""',
        "",
        "    def __init__(self, lib_path: str = None):",
        "        if lib_path is None:",
        f'            lib_path = Path(__file__).parent / "{module_name}.so"',
        "        self._lib = ctypes.CDLL(str(lib_path))",
        "        self._setup_signatures()",
        "",
        "    def _setup_signatures(self):",
    ]
    for fn in functions:
        ret_type = "ctypes.c_bool" if getattr(fn, 'return_type', None) == 'bool' else "ctypes.c_int64"
        lines.append(f"        self._lib.{fn.name}.restype = {ret_type}")
    lines.extend([
        "",
        "    @property",
        "    def state(self):",
        '        """Access managed state."""',
        "        return self._state",
        "    @state.setter",
        "    def state(self, value):",
        "        self._state = value",
        "",
    ])
    path.write_text("\n".join(lines) + "\n")


class ExportedFunction:
    """Simplified reflection of a parsed C function signature."""

    def __init__(self, name: str, params=None, return_type: str = "void"):
        self.name = name
        self.params = params or []
        self.return_type = return_type
