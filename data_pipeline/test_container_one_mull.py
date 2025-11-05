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
CONTAINER_NAME = "build-coreutils"

# ---------- container utilities (kept/adjusted from your script) ----------

def start_container(HOST_COREUTILS_PATH):
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


# ---------- configure with Mull ----------

def clean_build():
    """Run make clean to remove previous build artifacts."""
    print("  Running make clean...")
    r = run_in_container('make clean', show_output=False, timeout=120)
    if r.returncode == 0:
        print("  ✓ Make clean completed successfully")
        return True
    else:
        print("  ✗ Make clean failed (may be okay if first build)")
        print(f"  Return code: {r.returncode}")
        # Show output for debugging but don't fail - clean might fail if nothing to clean
        if r.stderr:
            print(f"  stderr: {r.stderr[:500]}")
        return True  # Don't fail on clean errors

def configure_with_mull():
    """Run configure with Mull instrumentation flags."""
    print("  Configuring with Mull instrumentation...")
    print("  Environment variables:")
    print("    FORCE_UNSAFE_CONFIGURE=1")
    print("    CC=clang-14")
    print("    C_INCLUDE_PATH=/coreutils/lib:/coreutils/unity")
    print("    CFLAGS=-fpass-plugin=/usr/lib/mull-ir-frontend-14 -g -grecord-command-line -fprofile-instr-generate -fcoverage-mapping")
    
    configure_cmd = """
export FORCE_UNSAFE_CONFIGURE=1
export CFLAGS="-fpass-plugin=/usr/lib/mull-ir-frontend-14 -g -grecord-command-line -fprofile-instr-generate -fcoverage-mapping"
CC=clang-14 C_INCLUDE_PATH="/coreutils/lib:/coreutils/unity" ./configure
"""
    print("  Running configure command...")
    r = run_in_container(configure_cmd, show_output=False, timeout=600)
    
    if r.returncode == 0:
        print("  ✓ Configure completed successfully")
        print(f"  Configure stdout (last 500 chars):\n{r.stdout[-500:]}")
        return True
    else:
        print("  ✗ Configure failed")
        print(f"  Return code: {r.returncode}")
        print(f"\n  Configure STDOUT (last 1000 chars):")
        print("  " + "="*50)
        print(r.stdout[-1000:] if r.stdout else "(empty)")
        print("  " + "="*50)
        print(f"\n  Configure STDERR (last 1000 chars):")
        print("  " + "="*50)
        print(r.stderr[-1000:] if r.stderr else "(empty)")
        print("  " + "="*50)
        return False


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
        print(f"  Return code: {r.returncode}")
        print(f"\n  Build STDOUT (last 800 chars):")
        print("  " + "="*50)
        print(r.stdout[-800:] if r.stdout else "(empty)")
        print("  " + "="*50)
        print(f"\n  Build STDERR (last 800 chars):")
        print("  " + "="*50)
        print(r.stderr[-800:] if r.stderr else "(empty)")
        print("  " + "="*50)
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

def run_mull(program_name, function_name):
    """Run Mull mutation testing and save output to file."""
    reports_dir = "mull-reports"
    mkdir_cmd = f"mkdir -p {reports_dir}"
    run_in_container(mkdir_cmd, show_output=False)
    
    # Save output to mull-reports directory
    output_file = f"{reports_dir}/mull_{program_name}_{function_name}.out"
    print(f"  Running Mull mutation testing...")
    print(f"  Command: mull-runner-14 src/{program_name} --debug")
    print(f"  Output will be saved to: {output_file}")
    
    mull_cmd = f'mull-runner-14 src/{program_name} --debug > {output_file} 2>&1'
    r = run_in_container(mull_cmd, show_output=False, timeout=600)
    
    print(f"  Mull command return code: {r.returncode}")
    
    # Check if output file was created and has content
    check_cmd = f'[ -f {output_file} ] && wc -l {output_file}'
    check_result = run_in_container(check_cmd, show_output=False)
    
    if check_result.returncode == 0:
        print(f"  ✓ Mull completed, output saved to {output_file}")
        print(f"    {check_result.stdout.strip()}")
        
        # Show a preview of the output
        preview_cmd = f'head -30 {output_file}'
        preview_result = run_in_container(preview_cmd, show_output=False)
        if preview_result.returncode == 0:
            print(f"  Preview of {output_file}:")
            print("  " + "-"*50)
            for line in preview_result.stdout.split('\n')[:30]:
                print(f"  {line}")
            print("  " + "-"*50)
        
        return True, output_file
    else:
        print(f"  ✗ Mull execution may have failed")
        print(f"  Check output stdout: {r.stdout[:500] if r.stdout else '(empty)'}")
        print(f"  Check output stderr: {r.stderr[:500] if r.stderr else '(empty)'}")
        return False, output_file


# ---------- file manipulation helpers ----------
def copy_results_back(temp_coreutils_path, original_coreutils_path):
    """Copy mutation testing results back to original directory."""
    print("Copying mutation testing results back to original directory...")
    
    # Copy mull-reports files if directory exists
    mull_reports_src = os.path.join(temp_coreutils_path, 'mull-reports')
    if os.path.exists(mull_reports_src):
        mull_reports_dest = os.path.join(original_coreutils_path, 'mull-reports')
        
        # Create destination directory if it doesn't exist
        os.makedirs(mull_reports_dest, exist_ok=True)
        
        # Copy each file individually (preserves other files, overwrites duplicates)
        for item in os.listdir(mull_reports_src):
            src_item = os.path.join(mull_reports_src, item)
            dest_item = os.path.join(mull_reports_dest, item)
            
            if os.path.isfile(src_item):
                shutil.copy2(src_item, dest_item)
                print(f"  ✓ Copied {item}")
            elif os.path.isdir(src_item):
                # For subdirectories, remove and replace
                if os.path.exists(dest_item):
                    shutil.rmtree(dest_item)
                shutil.copytree(src_item, dest_item)
                print(f"  ✓ Copied directory {item}")
        
        print(f"  ✓ Merged results into mull-reports/")
    else:
        print("  No mull-reports directory found")
        
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

def inject_and_test(program_name, HOST_COREUTILS_PATH, INJECTABLE_FUNCTION_PATH, run_mutation_testing=True):
    """
    For each injectable function (JSON at injectable_functions/<program>_injectable_functions.json),
    append that function's include to src/<program>/<program>.c, build, run tests, and restore original file.
    If run_mutation_testing is True, also run Mull after successful tests.
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
                results.append({
                    "function": function_name, 
                    "build": False, 
                    "test": False, 
                    "mull": False,
                    "build_output": build_out
                })
                # restore original before continuing
                write_host_file(src_c_path, original_code)
                print("  Restored code after failed build.")
                continue

            passed, stdout, stderr = run_tests(program_name)
            
            mull_success = False
            mull_output_file = None
            
            if passed and run_mutation_testing:
                print(f"  Function {function_name} passed tests. Running mutation testing...")
                mull_success, mull_output_file = run_mull(program_name, function_name)
            
            results.append({
                "function": function_name, 
                "build": True, 
                "test": passed, 
                "mull": mull_success,
                "mull_output": mull_output_file,
                "stdout": stdout, 
                "stderr": stderr
            })

            if passed:
                print(f"  ✓ Function {function_name} passed tests after injection.")
            
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
        if run_mutation_testing:
            status += f", mull={'✓' if r.get('mull') else '✗'}"
        print(f"  {r['function']}: {status}")
        if r.get('mull_output'):
            print(f"    Mull output: {r['mull_output']}")
    print("="*40)
    return results


def run_build_execute_mutate_for_one_coreutils_program(program_name, enable_mutation_testing):
    original_coreutils_path = os.path.join(SCRIPT_DIR, '..', 'coreutils')
    original_coreutils_path = os.path.abspath(original_coreutils_path)

    # Create a temporary copy of coreutils
    temp_dir = tempfile.mkdtemp(prefix='coreutils_tmp_')
    HOST_COREUTILS_PATH = os.path.join(temp_dir, 'coreutils')

    print(f"Creating temporary copy: {HOST_COREUTILS_PATH}")
    shutil.copytree(original_coreutils_path, HOST_COREUTILS_PATH, symlinks=True)

    # Compute injectable path from temp copy
    INJECTABLE_FUNCTION_PATH = os.path.join(HOST_COREUTILS_PATH, 'injectable_functions')
    

    try:
        if not start_container(HOST_COREUTILS_PATH):
            raise SystemExit("Failed to start container")

        # Configure with Mull instrumentation
        if enable_mutation_testing:
            print("\n" + "="*60)
            print("STEP 1: Clean previous build")
            print("="*60)
            if not clean_build():
                raise SystemExit("Failed to clean build")
            
            print("\n" + "="*60)
            print("STEP 2: Configure with Mull")
            print("="*60)
            if not configure_with_mull():
                raise SystemExit("Failed to configure with Mull")
        
        print("\n" + "="*60)
        print("STEP 3: Inject tests and build")
        print("="*60)
        inject_and_test(program_name, HOST_COREUTILS_PATH, INJECTABLE_FUNCTION_PATH, run_mutation_testing=enable_mutation_testing)

    finally:
        stop_container()
        # Copy results back to original coreutils directory
        copy_results_back(HOST_COREUTILS_PATH, original_coreutils_path)
        # Clean up temp directory
        print(f"Removing temporary directory: {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        print("  ✓ Cleanup complete")

if __name__ == "__main__":
    program_name = "pwd"  # change as needed
    enable_mutation_testing = True  # set to False to skip mutation testing
    run_build_execute_mutate_for_one_coreutils_program(program_name, enable_mutation_testing)