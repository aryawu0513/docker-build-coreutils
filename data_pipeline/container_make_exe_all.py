#!/usr/bin/env python3
"""
Build all programs and run tests for those with generated test files.

i.e.
I can just do make for all. and do the ./src/program for all programs that I have successfully genreated tests for. I can keep track of a list of them. But the list will just be all the programs that have a dir in the tests folder anyway.
"""

import os
import subprocess
import glob

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_COREUTILS_PATH = os.path.join(SCRIPT_DIR, '..', 'coreutils')
HOST_COREUTILS_PATH = os.path.abspath(HOST_COREUTILS_PATH)

if not os.path.exists(HOST_COREUTILS_PATH):
    print(f"ERROR: Coreutils directory not found at {HOST_COREUTILS_PATH}")
    exit(1)

print(f"Using coreutils path: {HOST_COREUTILS_PATH}")

CONTAINER_NAME = "coreutils-build"

def start_container():
    """Start a long-running container in the background"""
    check = subprocess.run(
        ['podman', 'ps', '-q', '-f', f'name={CONTAINER_NAME}'],
        capture_output=True,
        text=True
    )
    
    if check.stdout.strip():
        print(f"Container {CONTAINER_NAME} already running")
        return True
    
    subprocess.run(
        ['podman', 'rm', '-f', CONTAINER_NAME], 
        capture_output=True,
        text=True
    )
    
    print(f"Starting container {CONTAINER_NAME}...")
    result = subprocess.run([
        'podman', 'run', '-d',
        '--name', CONTAINER_NAME,
        '--user', 'root',
        '-v', f'{HOST_COREUTILS_PATH}:/coreutils',
        'build-coreutils',
        'sleep', 'infinity'
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"  ✓ Container started successfully")
        return True
    else:
        print(f"  ✗ Failed to start container: {result.stderr}")
        return False

def run_in_container(command):
    """Execute a command in the running container"""
    cmd = ['podman', 'exec', '-w', '/coreutils', CONTAINER_NAME, 'bash', '-c', command]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result

def stop_container():
    """Stop and remove the container"""
    print(f"Stopping container {CONTAINER_NAME}...")
    subprocess.run(['podman', 'stop', CONTAINER_NAME], capture_output=True)
    subprocess.run(['podman', 'rm', CONTAINER_NAME], capture_output=True)
    print("  ✓ Container stopped")

def build_all():
    """Run make to build all programs"""
    print("Building all coreutils programs...")
    result = run_in_container('make')
    
    if result.returncode == 0:
        print("  ✓ Build successful")
        return True
    else:
        print("  ✗ Build failed")
        print(f"    Error: {result.stderr[:1000]}")
        return False

def get_programs_with_test_dirs():
    """Get list of programs that have test directories"""
    tests_dir = os.path.join(HOST_COREUTILS_PATH, 'tests')
    test_dirs = glob.glob(f"{tests_dir}/*/")
    
    programs = []
    for test_dir in test_dirs:
        program_name = os.path.basename(os.path.normpath(test_dir))
        programs.append(program_name)
    
    return sorted(programs)

def run_tests_for_program(program_name):
    """Run tests for a single program"""
    print(f"  Testing {program_name}...")
    
    result = run_in_container(f'./src/{program_name}')
    
    if "FAIL" not in result.stdout and result.returncode == 0:
        print(f"    ✓ All tests passed")
        # Show test summary
        if "Tests" in result.stdout:
            lines = result.stdout.split('\n')
            for line in lines:
                if 'Tests' in line and ('Failures' in line or 'Ignored' in line):
                    print(f"      {line.strip()}")
        return True
    else:
        print(f"    ✗ Tests failed")
        print(f"      Output: {result.stdout[:300]}")
        return False

if __name__ == "__main__":
    try:
        # Start container
        if not start_container():
            exit(1)
        
        # Build all programs once
        if not build_all():
            print("Build failed, exiting")
            exit(1)
        
        # Get all programs with test directories
        programs = get_programs_with_test_dirs()
        print(f"\nFound {len(programs)} programs with test directories")
        print(f"Programs: {', '.join(programs[:10])}{'...' if len(programs) > 10 else ''}")
        
        # Run tests for each program
        print("\n" + "="*60)
        print("Running tests for all programs")
        print("="*60)
        
        passed = 0
        failed = 0
        
        for program in programs:
            if run_tests_for_program(program):
                passed += 1
            else:
                failed += 1
        
        # Summary
        print("\n" + "="*60)
        print(f"Test Summary:")
        print(f"  ✓ Passed: {passed}")
        print(f"  ✗ Failed: {failed}")
        print(f"  Total:  {passed + failed}")
        print("="*60)
        
    finally:
        stop_container()