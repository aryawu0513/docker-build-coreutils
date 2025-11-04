#!/usr/bin/env python3
"""
Build & test loop: for each injectable function, append its test-include to the
target C file, build inside the running container, run tests, collect results,
and restore the original source file.
"""

import os
import subprocess
import json
import shutil
import tempfile
from tree_sitter import Language, Parser
import tree_sitter_c as tsc
from test_gpt5_generation import remove_main_with_treesitter

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_COREUTILS_PATH = os.path.join(SCRIPT_DIR, '..', 'coreutils')
HOST_COREUTILS_PATH = os.path.abspath(HOST_COREUTILS_PATH)
INJECTABLE_FUNCTION_PATH = os.path.join(HOST_COREUTILS_PATH, 'injectable_functions')

CONTAINER_NAME = "build-coreutils"

# ---------- container utilities (kept/adjusted from your script) ----------

def start_container():
    """Start a long-running container in the background (clean start)."""
    subprocess.run(['podman', 'rm', '-f', CONTAINER_NAME],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Starting container {CONTAINER_NAME}...")
    result = subprocess.run([
        'podman', 'run', '-d', '--name', CONTAINER_NAME, '--user', 'root',
        '-v', f'{HOST_COREUTILS_PATH}:/coreutils', 'build-coreutils', 'sleep', 'infinity'
    ], capture_output=True, text=True)
    if result.returncode == 0:
        print("  ✓ Container started successfully")
        return True
    else:
        print(f"  ✗ Failed to start container: {result.stderr}")
        return False

def run_in_container(command, show_output=False, timeout=120):
    """Run command in container; returns subprocess.CompletedProcess."""
    # cmd = ['podman', 'exec', '-w', '/coreutils', CONTAINER_NAME, 'bash', '-c', command]
    cmd = ['podman', 'exec', '-t', '-w', '/coreutils', CONTAINER_NAME, 'bash', '-c', command]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"⚠ Command timed out after {timeout}s: {command}")
        result = subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="Timeout expired")
    if show_output:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
    return result

def stop_container():
    """Stop and remove the container."""
    print(f"Stopping container {CONTAINER_NAME}...")
    subprocess.run(['podman', 'stop', CONTAINER_NAME], capture_output=True)
    subprocess.run(['podman', 'rm', CONTAINER_NAME], capture_output=True)
    print("  ✓ Container stopped")


# ---------- build / test helpers ----------

def build_program(program_name):
    """Build a single program inside container (make src/<program_name>)."""
    print(f"  Building src/{program_name}...")
    r = run_in_container(f'make src/{program_name}', show_output=False, timeout=300)
    if r.returncode == 0:
        print(f"  ✓ Built src/{program_name}")
        return True, r.stdout
    else:
        print(f"  ✗ Build failed for src/{program_name}")
        # show some stderr for debugging
        print(r.stderr[:800])
        return False, r.stderr

def run_tests(program_name):
    """Run the compiled program inside container and capture output."""
    print(f"  Running tests: ./src/{program_name}")
    r = run_in_container(f'./src/{program_name}', show_output=False, timeout=120)
    # Consider "FAIL" in stdout as a failing test; otherwise returncode 0 is success.
    passed = (r.returncode == 0) and ("FAIL" not in (r.stdout or ""))
    if passed:
        print(f"  ✓ Tests passed for {program_name}")
    else:
        print(f"  ✗ Tests failed / non-zero exit for {program_name}")
        # show a truncated output for diagnostics
        print((r.stdout or "")[:1000])
        print((r.stderr or "")[:1000])
    return passed, r.stdout, r.stderr


# ---------- file manipulation helpers ----------

def append_include_line_to_code(code_without_main, include_line):
    """Return new code string with include_line appended if absent."""
    lines = code_without_main.splitlines()
    if include_line in lines:
        return '\n'.join(lines) + '\n'  # unchanged (but normalized newline)
    lines.append(include_line)
    return '\n'.join(lines) + '\n'

def write_host_file(path, content):
    """Write content to host path atomically using temp file."""
    dirpath = os.path.dirname(path)
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dirpath, prefix='.tmp_write_')
    os.close(fd)
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    # atomic move
    shutil.move(tmp, path)


# ---------- main inject-and-test logic ----------

def inject_and_test(program_name):
    """
    For each injectable function (JSON at injectable_functions/<program>_injectable_functions.json),
    append that function's include to src/<program>/<program>.c, build, run tests, and restore original file.
    """
    C_LANGUAGE = Language(tsc.language())
    parser = Parser(C_LANGUAGE)

    injectable_json = os.path.join(INJECTABLE_FUNCTION_PATH, f"{program_name}_injectable_functions.json")
    if not os.path.exists(injectable_json):
        print(f"No injectable JSON found: {injectable_json}")
        return

    # load injectable functions
    with open(injectable_json, 'r', encoding='utf-8') as f:
        injectable_functions = json.load(f)

    src_c_path = os.path.join(HOST_COREUTILS_PATH, 'src', f"{program_name}.c")
    if not os.path.exists(src_c_path):
        print(f"ERROR: source file not found: {src_c_path}")
        return

    # backup original
    with open(src_c_path, 'r', encoding='utf-8') as f:
        original_code = f.read()
    original_code_without_main = remove_main_with_treesitter(src_c_path, parser).decode('utf-8')
    results = []

    try:
        for func in injectable_functions:
            function_name = func.get("function_name") or func.get("name") or "<unknown>"
            include_line = func.get("include_line")
            if not include_line:
                print(f"Skipping {function_name}: no include_line")
                continue

            print("\n" + "-"*60)
            print(f"Processing function: {function_name}")
            # create modified code by appending include
            modified_code = append_include_line_to_code(original_code_without_main, include_line)

            # write modified code back to host file (visible inside container)
            write_host_file(src_c_path, modified_code)
            print(f"  Wrote modified {src_c_path} (include: {include_line})")

            # build and run
            built, build_out = build_program(program_name)
            if not built:
                results.append({"function": function_name, "build": False, "test": False, "build_output": build_out})
                # restore original before continuing
                write_host_file(src_c_path, original_code)
                print("  Restored code after failed build.")
                continue

            passed, stdout, stderr = run_tests(program_name)
            results.append({"function": function_name, "build": True, "test": passed, "stdout": stdout, "stderr": stderr})

            # restore original file (so next iteration starts from clean source)
            write_host_file(src_c_path, original_code)
            print("  Restored original source file after test run.")

    finally:
        # ensure source restored even if exception occurs
        if os.path.exists(src_c_path):
            write_host_file(src_c_path, original_code)

    # Print summary
    print("\n" + "="*40)
    print(f"Results for program {program_name}:")
    for r in results:
        status = f"build={'✓' if r['build'] else '✗'}, test={'✓' if r['test'] else '✗'}"
        print(f"  {r['function']}: {status}")
    print("="*40)
    return results


# ----------------- run as script -----------------

if __name__ == "__main__":
    program = "date"  # change as needed
    try:
        if not start_container():
            raise SystemExit("Failed to start container")

        inject_and_test(program)

    finally:
        stop_container()
