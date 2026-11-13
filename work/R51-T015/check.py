#!/usr/bin/env python3
"""Run matrix verification, isolation checks, and repository native test suite."""

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


WORK_DIR = Path(__file__).resolve().parent
ROOT = WORK_DIR.parents[1]
TEST_PATH = "src/algorithms/image-processing/seam-carving/__tests__/resizeImageWidth.node.js"
TOOL_VERSIONS_FILE = WORK_DIR / "tool-versions.json"
CASES_FILE = WORK_DIR / "cases.json"
FOCUSED_JEST_RESULTS_FILE = WORK_DIR / "focused-jest-results.json"
JEST_RESULTS_FILE = WORK_DIR / "jest-results.json"
NATIVE_TEST_SUMMARY_FILE = WORK_DIR / "native-test-summary.json"
RESULTS_FILE = WORK_DIR / "results.json"
TEST_RUN_LOG = WORK_DIR / "test-run.log"
MUTATION_LOG = WORK_DIR / "mutation-check.log"


def run(command, cwd=ROOT, env=None):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def get_tool_versions():
    node_version = subprocess.check_output(
        ["node", "--version"],
        cwd=ROOT,
        text=True,
    ).strip()
    npm_version = subprocess.check_output(
        ["npm", "--version"],
        cwd=ROOT,
        text=True,
    ).strip()
    return {
        "python": platform.python_version(),
        "node": node_version,
        "npm": npm_version,
    }


def read_jest_results(path):
    with path.open(encoding="utf-8") as file:
        results = json.load(file)
    return {
        "totalTests": results.get("numTotalTests", 0),
        "passedTests": results.get("numPassedTests", 0),
        "failedTests": results.get("numFailedTests", 0),
        "pendingTests": results.get("numPendingTests", 0),
        "testSuites": results.get("numTotalTestSuites", 0),
    }


def validate_matrix_cases(cases):
    required_fixtures = {
        "small rectangular matrix": False,
        "1x1 matrix": False,
        "zero-containing matrix": False,
    }

    for case in cases:
        fixture_name = case.get("fixture")
        if fixture_name in required_fixtures:
            required_fixtures[fixture_name] = True

        expected = case.get("expected")
        actual = case.get("actual")
        if actual != expected:
            raise ValueError(
                f"Assertion failed for case {case}: expected {expected}, got {actual}"
            )

    missing = [name for name, found in required_fixtures.items() if not found]
    if missing:
        raise ValueError(f"Missing required fixture cases in evidence: {missing}")


def run_mutation_check():
    """Verify that our tests catch a broken/mutated matrix implementation."""
    with tempfile.TemporaryDirectory(prefix="matrix-mutation-") as temp_dir:
        sandbox = Path(temp_dir)
        shutil.copytree(ROOT / "src", sandbox / "src")
        for filename in (".babelrc", "jest.config.js", "package.json"):
            shutil.copy2(ROOT / filename, sandbox / filename)
        (sandbox / "node_modules").symlink_to(
            ROOT / "node_modules",
            target_is_directory=True,
        )

        target_file = (
            sandbox / "src/algorithms/image-processing/seam-carving/resizeImageWidth.js"
        )
        source = target_file.read_text(encoding="utf-8")

        # Mutate matrix: share a single row array across all rows (breaking row isolation)
        original_impl = (
            "export const matrix = (w, h, filler) => {\n"
            "  return new Array(h)\n"
            "    .fill(null)\n"
            "    .map(() => {\n"
            "      return new Array(w).fill(filler);\n"
            "    });\n"
            "};"
        )
        mutated_impl = (
            "export const matrix = (w, h, filler) => {\n"
            "  const sharedRow = new Array(w).fill(filler);\n"
            "  return new Array(h).fill(sharedRow);\n"
            "};"
        )
        if original_impl not in source:
            raise RuntimeError("Could not find matrix implementation to mutate in sandbox")

        target_file.write_text(
            source.replace(original_impl, mutated_impl),
            encoding="utf-8",
        )

        mutation_results_path = sandbox / "jest-results.json"
        cmd = [
            "npm",
            "test",
            "--",
            "--runInBand",
            "--runTestsByPath",
            TEST_PATH,
            "--json",
            "--outputFile=jest-results.json",
        ]
        result = run(cmd, sandbox)
        mutation = {
            "command": " ".join(cmd),
            "exitCode": result.returncode,
            "output": result.stdout,
        }
        if mutation_results_path.exists():
            mutation.update(read_jest_results(mutation_results_path))
        else:
            mutation.update({"totalTests": 0, "passedTests": 0, "failedTests": 0})
        return mutation


def main():
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Capture tool versions
    versions = get_tool_versions()
    TOOL_VERSIONS_FILE.write_text(
        json.dumps(versions, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Tool versions: {versions}")

    # 2. Install dependencies via lockfile
    print("\nRunning npm ci...")
    install_res = run(["npm", "ci"])
    if install_res.returncode != 0:
        print(f"npm ci failed:\n{install_res.stdout}", file=sys.stderr)
        return install_res.returncode
    print("npm ci completed successfully.")

    # 3. Run focused tests and extract evidence cases
    print(f"\nRunning focused checks on {TEST_PATH}...")
    env = os.environ.copy()
    env["MATRIX_EVIDENCE_PATH"] = str(CASES_FILE)
    focused_cmd = [
        "npm",
        "test",
        "--",
        "--runInBand",
        "--runTestsByPath",
        TEST_PATH,
        "--json",
        f"--outputFile={FOCUSED_JEST_RESULTS_FILE.relative_to(ROOT)}",
    ]
    focused_res = run(focused_cmd, env=env)
    print(focused_res.stdout)
    if focused_res.returncode != 0:
        print("Focused checks failed!", file=sys.stderr)
        return focused_res.returncode

    if not CASES_FILE.exists():
        print(f"Error: {CASES_FILE} was not generated", file=sys.stderr)
        return 1

    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    validate_matrix_cases(cases)
    print(f"Validated {len(cases)} matrix execution evidence cases successfully.")

    focused_summary = read_jest_results(FOCUSED_JEST_RESULTS_FILE)
    print(f"Focused Jest results: {focused_summary}")

    # 4. Run mutation check
    print("\nRunning mutation verification to ensure test sensitivity...")
    mutation = run_mutation_check()
    MUTATION_LOG.write_text(mutation["output"], encoding="utf-8")
    mutation_detected = (
        mutation["exitCode"] != 0 or mutation.get("failedTests", 0) > 0
    )
    print(
        f"Mutation detected: {mutation_detected} "
        f"(exit code: {mutation['exitCode']}, failed tests: {mutation.get('failedTests', 0)})"
    )
    if not mutation_detected:
        print("Error: Deliberate mutation was not detected by the test suite!", file=sys.stderr)
        return 1

    # 5. Run full native test suite in non-watch mode
    print("\nRunning repository native test suite...")
    native_cmd = [
        "npm",
        "test",
        "--",
        "--runInBand",
        "--json",
        f"--outputFile={JEST_RESULTS_FILE.relative_to(ROOT)}",
    ]
    native_res = run(native_cmd)
    TEST_RUN_LOG.write_text(native_res.stdout, encoding="utf-8")
    print(f"Native test run exited with code {native_res.returncode}")

    if not JEST_RESULTS_FILE.exists():
        print("Error: native test output jest-results.json not found", file=sys.stderr)
        return 1

    native_summary = read_jest_results(JEST_RESULTS_FILE)
    print(f"Native Jest summary: {native_summary}")

    native_summary_data = {
        "command": " ".join(native_cmd),
        "exit_code": native_res.returncode,
        "total_tests": native_summary["totalTests"],
        "passed_tests": native_summary["passedTests"],
        "failed_tests": native_summary["failedTests"],
        "pending_tests": native_summary["pendingTests"],
        "test_suites": native_summary["testSuites"],
    }
    NATIVE_TEST_SUMMARY_FILE.write_text(
        json.dumps(native_summary_data, indent=2) + "\n",
        encoding="utf-8",
    )

    if native_res.returncode != 0 or native_summary["failedTests"] > 0:
        print("Error: Native test suite has failures!", file=sys.stderr)
        return 1

    # 6. Save comprehensive results.json
    results = {
        "versions": versions,
        "code_inspection": {
            "target": "matrix (around line 49)",
            "file": "src/algorithms/image-processing/seam-carving/resizeImageWidth.js",
            "public_inputs": [
                {"name": "w", "type": "number", "description": "Width (columns)"},
                {"name": "h", "type": "number", "description": "Height (rows)"},
                {"name": "filler", "type": "?(number | SeamPixelMeta)", "description": "Fill value"},
            ],
            "return_value": "2D array (h rows x w columns) filled with specified filler value",
            "mutation_behavior": "Pure, non-mutating. Allocates new outer Array(h) and distinct inner Array(w) per row.",
            "external_dependencies": "None. Does not rely on time, randomness, network, UI, filesystem, or global state.",
        },
        "install_command": "npm ci",
        "install_exit_code": install_res.returncode,
        "focused_check": {
            "command": " ".join(focused_cmd),
            "exit_code": focused_res.returncode,
            "test_count": focused_summary,
        },
        "mutation_check": {
            "command": mutation["command"],
            "detected": mutation_detected,
            "exit_code": mutation["exitCode"],
            "failed_tests": mutation.get("failedTests", 0),
        },
        "native_check": native_summary_data,
        "cases": cases,
    }
    RESULTS_FILE.write_text(
        json.dumps(results, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nAll checks passed. Evidence saved in {WORK_DIR.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

