"""
backends.py — Registry of Veri DSL verification backends.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class BackendConfig:
    name: str
    target: str
    fixture: str
    has_compile_pipeline: bool = True
    has_docker: bool = False
    docker_agent: Optional[str] = None
    has_converter: bool = False
    has_parser: bool = False
    has_runtime_lib: bool = False
    env: Dict[str, str] = field(default_factory=dict)
    skip_reason: Optional[str] = None


BACKENDS: Dict[str, BackendConfig] = {
    "fstar": BackendConfig(
        name="F*",
        target="fstar",
        fixture="sorted_list.veri.md",
        has_docker=True,
        docker_agent="claude",
        has_converter=True,
        has_parser=True,
    ),
    "dafny": BackendConfig(
        name="Dafny",
        target="dafny",
        fixture="circular_buffer.veri.md",
        has_docker=True,
        docker_agent="openclaw",
        has_converter=False,
        has_parser=True,
    ),
    "python": BackendConfig(
        name="Python",
        target="python-assert",
        fixture="sorted_list.veri.md",
        has_compile_pipeline=False,
        has_docker=True,
        docker_agent="claude",
        has_converter=False,
        has_parser=False,
        has_runtime_lib=True,
    ),
}


def get_backend(name: str) -> BackendConfig:
    if name not in BACKENDS:
        known = ", ".join(sorted(BACKENDS.keys()))
        raise KeyError(f"Unknown backend '{name}'. Known backends: {known}")
    return BACKENDS[name]


def enabled_backends() -> Dict[str, BackendConfig]:
    return {n: c for n, c in BACKENDS.items() if c.skip_reason is None}


def compile_pipeline_backends() -> Dict[str, BackendConfig]:
    return {n: c for n, c in BACKENDS.items() if c.has_compile_pipeline and c.skip_reason is None}


def docker_backends() -> Dict[str, BackendConfig]:
    return {n: c for n, c in BACKENDS.items() if c.has_docker and c.skip_reason is None}


def agent_backends() -> Dict[str, BackendConfig]:
    return {n: c for n, c in BACKENDS.items() if c.docker_agent and c.skip_reason is None}


def converter_backends() -> Dict[str, BackendConfig]:
    return {n: c for n, c in BACKENDS.items() if c.has_converter and c.skip_reason is None}


def runtime_backends() -> Dict[str, BackendConfig]:
    return {n: c for n, c in BACKENDS.items() if c.has_runtime_lib and c.skip_reason is None}
