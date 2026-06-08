"""
End-to-end pipeline scenario tests — full Veri DSL → F* → Veri DSL roundtrip.

Covers the complete compile_veri → convert back flow, verifying that
all pipeline stages wire together correctly.
"""

import sys
import json
from pathlib import Path

from common import (
    FIXTURES, RESULTS_DIR,
    save_result, log_step, skip_unless,
    extract_veri_blocks, pipeline_config,
)


# ═════════════════════════════════════════════════════════════════════════
# Scenario: End-to-End Pipeline
# ═════════════════════════════════════════════════════════════════════════

def test_scenario_compile_pipeline():
    """Scenario: Veri DSL → F* → Veri DSL via local pipeline (no Docker)."""
    veri_path = FIXTURES / "sorted_list.veri.md"
    veri_text = veri_path.read_text()
    blocks = extract_veri_blocks(veri_text)
    assert len(blocks) >= 1
    joined_veri = "\n\n".join(blocks)

    from veri_parser import parse_veri
    from veri_printer import VeriDslPrinter
    from veri_build.pipeline import compile_veri, convert_fstar_to_veri

    prog = parse_veri(joined_veri)
    assert prog is not None
    assert len(prog.decls) >= 3

    reprinted = VeriDslPrinter().print(prog)
    assert "SortedList" in reprinted or "sorted_list" in reprinted

    config = pipeline_config("fstar")
    result = compile_veri(str(veri_path), config)
    assert result.success
    assert result.interface is not None

    veri_from_target = convert_fstar_to_veri(result.interface)
    assert veri_from_target is not None

    save_result("scenario_compile", {
        "original_decls": len(prog.decls),
        "interface_length": len(result.interface),
        "veri_from_target_length": len(veri_from_target),
    })
    log_step(
        f"Scenario: {len(prog.decls)} decls → {len(result.interface)} F* "
        f"→ {len(veri_from_target)} Veri DSL"
    )


# ═════════════════════════════════════════════════════════════════════════
# Report: Generate test summary
# ═════════════════════════════════════════════════════════════════════════

def test_report_generate():
    """Generate a summary report of all test result files."""
    from common import DOCKER_AVAILABLE, OPENCLAW_AVAILABLE, RESULTS_DIR

    reports = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        reports.append({"file": f.name, "keys": list(data.keys())})

    report_data = {
        "test_count": len(reports),
        "results": reports,
        "env": {
            "docker": DOCKER_AVAILABLE,
            "openclaw": OPENCLAW_AVAILABLE,
        },
    }
    save_result("_report", report_data)
    log_step(f"Integration report: {len(reports)} result files")
