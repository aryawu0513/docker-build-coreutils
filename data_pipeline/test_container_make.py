#!/usr/bin/env python3
"""
Functions to build and test coreutils programs in a container.
"""

import os
import subprocess

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_COREUTILS_PATH = os.path.join(SCRIPT_DIR, '..', 'coreutils')
HOST_COREUTILS_PATH = os.path.abspath(HOST_COREUTILS_PATH)

# Verify coreutils exists
if not os.path.exists(HOST_COREUTILS_PATH):
    print(f"ERROR: Coreutils directory not found at {HOST_COREUTILS_PATH}")
    exit(1)

print(f"Using coreutils path: {HOST_COREUTILS_PATH}")

CONTAINER_NAME = "coreutils-build"

def start_container():
    """Start a long-running container in the background"""
    # Check if container already running
    check = subprocess.run(
        ['podman', 'ps', '-q', '-f', f'name={CONTAINER_NAME}'],
        capture_output=True,
        text=True
    )
    
    if check.stdout.strip():
        print(f"Container {CONTAINER_NAME} already running")
        return True
    
    # Remove old container if exists - FIX THIS LINE
    subprocess.run(
        ['podman', 'rm', '-f', CONTAINER_NAME], 
        capture_output=True,  # Remove stderr=subprocess.DEVNULL
        text=True
    )
    
    # Start container
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

def run_in_container(command, show_output=False):
    """Execute a command in the running container"""
    cmd = ['podman', 'exec', '-w', '/coreutils', CONTAINER_NAME, 'bash', '-c', command]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if show_output:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
    
    return result

def stop_container():
    """Stop and remove the container"""
    print(f"Stopping container {CONTAINER_NAME}...")
    subprocess.run(['podman', 'stop', CONTAINER_NAME], capture_output=True)
    subprocess.run(['podman', 'rm', CONTAINER_NAME], capture_output=True)
    print("  ✓ Container stopped")

def build_program(program_name):
    """Build the program using make inside container"""
    print(f"  Building src/{program_name}...")
    
    result = run_in_container(f'make src/{program_name}')
    
    if result.returncode == 0:
        print(f"  ✓ Built src/{program_name} successfully")
        return True
    else:
        print(f"  ✗ Build failed for src/{program_name}")
        print(f"    Error: {result.stderr[:500]}")
        return False

def run_tests(program_name):
    """Run the compiled program to execute tests inside container"""
    print(f"  Running tests for {program_name}...")
    
    result = run_in_container(f'./src/{program_name}')
    
    if "FAIL" not in result.stdout and result.returncode == 0:
        print(f"  ✓ All tests passed for {program_name}")
        # Count tests
        if "Tests" in result.stdout:
            lines = result.stdout.split('\n')
            for line in lines:
                if 'Tests' in line and ('Failures' in line or 'Ignored' in line):
                    print(f"    {line.strip()}")
        return True
    else:
        print(f"  ✗ Tests failed for {program_name}")
        print(f"    Output: {result.stdout[:500]}")
        return False

if __name__ == "__main__":
    # Example usage
    try:
        start_container()
        
        # Test cat
        build_program("cat")
        run_tests("cat")
        
        # Test more programs
        # build_program("ls")
        # run_tests("ls")
        
    finally:
        stop_container()