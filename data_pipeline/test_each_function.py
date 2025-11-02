import os
import subprocess
import glob
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_c as tsc
import re

# Configuration
COREUTILS_ROOT = "/home/aryawu/docker-build-coreutils/coreutils"
SRC_DIR = f"{COREUTILS_ROOT}/src"
TESTS_DIR = f"{COREUTILS_ROOT}/tests"
UNITY_DIR = f"{COREUTILS_ROOT}/unity"

def extract_program_name(c_file):
    """Extract program name from .c file (e.g., cat.c -> cat)"""
    return Path(c_file).stem

def remove_header_comments(content):
    """Remove all leading comment lines and empty lines"""
    lines = content.split('\n')
    
    # Skip all lines starting with # or empty lines from the top
    while lines and (lines[0].strip().startswith('#') or not lines[0].strip()):
        lines.pop(0)
    
    return '\n'.join(lines)

def read_shell_tests(program_name):
    """Read content of all shell test files"""
    tests_content = []
    test_dir = f"{TESTS_DIR}/{program_name}"
    if not os.path.exists(test_dir):
        return []
    
    shell_test_files = glob.glob(f"{test_dir}/*.sh")
    
    for test_file in shell_test_files:
        with open(test_file, 'r') as f:
            tests_content.append({
                'filename': os.path.basename(test_file),
                'content': remove_header_comments(f.read())
            })
    return tests_content

def remove_main_with_treesitter(c_file):
    """Use tree-sitter to remove main() function from C file"""
    # Load C parser
    C_LANGUAGE = Language(tsc.language())
    parser = Parser(C_LANGUAGE)
    
    # Read the file
    with open(c_file, 'rb') as f:
        source_code = f.read()
    
    # Parse the code
    tree = parser.parse(source_code)
    root_node = tree.root_node
    
    # Find main function
    def find_main_function(node):
        if node.type == 'function_definition':
            # Check if this is the main function
            for child in node.children:
                if child.type == 'function_declarator':
                    for subchild in child.children:
                        if subchild.type == 'identifier' and source_code[subchild.start_byte:subchild.end_byte] == b'main':
                            return node
        
        for child in node.children:
            result = find_main_function(child)
            if result:
                return result
        return None
    
    main_node = find_main_function(root_node)
    
    if main_node:
        # Remove the main function
        start_byte = main_node.start_byte
        end_byte = main_node.end_byte
        
        new_source = source_code[:start_byte] + source_code[end_byte:]
        
        # Write back
        with open(c_file, 'wb') as f:
            f.write(new_source)
        
        print(f"  ✓ Removed main() from {c_file}")
        return True
    else:
        print(f"  ⚠ No main() found in {c_file}")
        return False


def add_test_include(c_file, program_name):
    """Add #include for test file right after #include <config.h>"""
    include_line = f'#include "../tests/{program_name}/{program_name}_tests.c"'
    
    with open(c_file, 'r') as f:
        content = f.read()
    
    # Check if already included
    if include_line in content:
        print(f"  ⚠ Test include already exists in {c_file}")
        return True
    
    lines = content.split('\n')
    
    # Find config.h include line (handles both "#include" and "# include")
    config_h_pos = None
    for i, line in enumerate(lines):
        # Match: #include <config.h> or # include <config.h>
        if re.search(r'^\s*#\s*include\s*[<"]config\.h[>"]', line):
            config_h_pos = i
            break
    
    # If no config.h found, skip this file
    if config_h_pos is None:
        print(f"  ⊘ No config.h found in {c_file} - skipping (likely helper/variant/generator)")
        return False
    
    # Insert test include right after config.h
    lines.insert(config_h_pos + 1, include_line)
    
    with open(c_file, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f"  ✓ Added test include to {c_file} (after config.h)")
    return True

#I want this to be a DSPY function that calls GPT-5
def generate_unity_tests_with_llm(program_name, shell_tests):
    return False


import subprocess

CONTAINER_NAME = "coreutils-build"  # You'll need to name your container

def ensure_container_running():
    """Check if container is running, start it if not"""
    # Check if container exists and is running
    result = subprocess.run(
        ['podman', 'ps', '-q', '-f', f'name={CONTAINER_NAME}'],
        capture_output=True,
        text=True
    )
    
    if result.stdout.strip():
        return True  # Container is running
    
    # Check if container exists but is stopped
    result = subprocess.run(
        ['podman', 'ps', '-a', '-q', '-f', f'name={CONTAINER_NAME}'],
        capture_output=True,
        text=True
    )
    
    if result.stdout.strip():
        # Container exists but stopped, start it
        print(f"Starting existing container {CONTAINER_NAME}...")
        subprocess.run(['podman', 'start', CONTAINER_NAME])
        return True
    
    # Container doesn't exist, create and start it
    print(f"Creating container {CONTAINER_NAME}...")
    subprocess.run([
        'podman', 'run', '-d', '--name', CONTAINER_NAME,
        '--user', 'root',
        '-v', f'{os.getcwd()}/coreutils:/coreutils',
        'build-coreutils',
        'sleep', 'infinity'  # Keep container running
    ])
    return True

def run_in_container(command):
    """Run a command inside the container"""
    ensure_container_running()
    
    result = subprocess.run(
        ['podman', 'exec', '-w', '/coreutils', CONTAINER_NAME] + command,
        capture_output=True,
        text=True
    )
    return result

def build_program(program_name):
    """Build the program using make inside container"""
    print(f"  Building src/{program_name} in container...")
    
    result = run_in_container(['make', f'src/{program_name}'])
    
    if result.returncode == 0:
        print(f"  ✓ Built src/{program_name} successfully")
        return True
    else:
        print(f"  ✗ Build failed for src/{program_name}")
        print(f"    Error: {result.stderr[:500]}")
        return False

def run_tests(program_name):
    """Run the compiled program to execute tests inside container"""
    print(f"  Running tests for {program_name} in container...")
    
    result = run_in_container([f'./src/{program_name}'])
    
    if "FAIL" not in result.stdout and result.returncode == 0:
        print(f"  ✓ All tests passed for {program_name}")
        # Count tests
        if "Tests" in result.stdout:
            test_count = result.stdout.split('Tests')[0].strip().split()[-1]
            print(f"    {test_count} tests passed")
        return True
    else:
        print(f"  ✗ Tests failed for {program_name}")
        print(f"    Output: {result.stdout[:500]}")
        return False



if __name__ == "__main__":
    example_file = "/home/aryawu/docker-build-coreutils/data_pipeline/cksum.c"
    #1. Extract program name
    program_name = extract_program_name(example_file)
    #2. Find shell tests
    shell_tests_contents = read_shell_tests(program_name)
    #3. Generate Unity tests with LLM
    generate_tests_success = generate_unity_tests_with_llm(program_name, shell_tests_contents)
    #4. use tree-sitter to remove main()
    remove_main_with_treesitter(example_file)
    #5. Add test include after config.h
    add_test_include(example_file, program_name)
    # We will do the build and execute tests in container for all together later.