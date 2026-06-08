# Veri DSL Integration — Test Fixtures & Results

This directory holds **static fixture files** and **test run output** for the
Veri DSL verification pipeline integration tests. The actual test code lives in
`tests/test_fstar.py`, `tests/test_dafny.py`, etc.

## Fixtures

| File | Target | Features |
|------|--------|----------|
| `fixtures/sorted_list.veri.md` | F* → C | Records, refined types, list patterns, contracts, TARGET declaration |
| `fixtures/circular_buffer.veri.md` | Dafny → Rust | Constants, match/case, buffer invariants, TARGET declaration |
| `fixtures/sorted_list.fsti` | Raw F* | Direct F* → Veri DSL conversion test |

## Results

After running the tests, `results/` contains JSON files keyed by flow name:

```
results/
├── flow1_fstar_interface.json     # Veri DSL → F* generation output
├── flow1_verify_convert.json      # F*F* → Veri DSL verify_and_convert
├── flow2_dafny_interface.json     # Veri DSL → Dafny generation output
├── flow3_convert_fstar.json       # Direct F* → Veri DSL conversion
├── flow3_veri_roundtrip.json       # Veri DSL → AST → Veri DSL roundtrip
├── flow4_docker_fstar.json        # Docker F* pipeline
├── flow4_docker_dafny.json        # Docker Dafny pipeline
├── flow5_agent_fstar_claude.json  # Claude Code agent results
├── flow5_agent_dafny_openclaw.json # OpenClaw agent results
├── flow6_openclaw_health.json     # OpenClaw gateway health
├── flow7_dsl_completeness.json    # Cross-backend coverage
├── scenario_compile.json          # End-to-end scenario
├── python_conditions_gen.json     # Python conditions generation
├── python_ast_match.json          # Python AST comparison
├── python_decorator_verify.json   # Python decorator verification
└── _report.json                   # Summary
```

## Adding a Fixture

1. Create a `.veri.md` file in `fixtures/` following this template:
   ````markdown
   # <Name>

   ```veri
   TARGET f-star-c  # or dafny-rust or python-assert

   <Veri DSL declarations>
   ```
   ````
2. Add a test function in the appropriate `tests/test_*.py` file
3. Run: `python3 -m pytest tests/ -v -k <your_test>`
