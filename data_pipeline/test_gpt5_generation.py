import dspy
import os
from tree_sitter import Language, Parser
import tree_sitter_c as tsc
import re
from pathlib import Path
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_COREUTILS_PATH = os.path.join(SCRIPT_DIR, '..', 'coreutils')
HOST_COREUTILS_PATH = os.path.abspath(HOST_COREUTILS_PATH)
INJECTABLE_FUNCTION_PATH = os.path.join(HOST_COREUTILS_PATH, 'injectable_functions')


def get_function_info(c_file, parser):
    """
    Extract detailed information about all functions (except main).
    
    Args:
        c_file: Path to the C source file
        parser: tree-sitter Parser instance
    
    Returns:
        List of dicts with keys: 'name', 'start_byte', 'end_byte', 'code', 'signature'
    """
    # Parse the code
    with open(c_file, 'rb') as f:
        c_code = f.read()
    tree = parser.parse(c_code)
    
    functions = []
    
    def get_function_signature(func_def_node):
        """Extract the function signature (return type + declarator)"""
        signature_parts = []
        
        for child in func_def_node.children:
            # Get everything before the compound_statement (function body)
            if child.type == 'compound_statement':
                break
            signature_parts.append(c_code[child.start_byte:child.end_byte])
        
        return b' '.join(signature_parts).decode('utf-8').strip()
    
    def filter_trivial_function(func_code, min_lines):
        """Return True if function has fewer than min_lines of code"""
        # Count non-empty lines
        lines = [line for line in func_code.splitlines() if line.strip()]
        return len(lines) < min_lines
        
    def traverse_tree(node):
        """Recursively traverse to find function definitions"""
        if node.type == 'function_definition':
            # Extract function name
            func_name = None
            for child in node.children:
                if child.type == 'function_declarator':
                    for subchild in child.children:
                        if subchild.type == 'identifier':
                            func_name = c_code[subchild.start_byte:subchild.end_byte].decode('utf-8')
                            break
                    break
            
            # Skip main function
            if func_name and func_name != 'main':
                func_code = c_code[node.start_byte:node.end_byte].decode('utf-8')
                
                # Skip functions that are too small
                if filter_trivial_function(func_code, 10):
                    return
                
                signature = get_function_signature(node)
                
                functions.append({
                    'name': func_name,
                    'start_byte': node.start_byte,
                    'end_byte': node.end_byte,
                    'code': func_code,
                    'signature': signature
                })
        
        # Recursively traverse children
        for child in node.children:
            traverse_tree(child)
    
    traverse_tree(tree.root_node)
    return functions

class FunctionToUnityTests(dspy.Signature):
    """
    You will be given a coreutils program and the name of a SPECIFIC FUNCTION within it.
    Your task is to write a standalone test suite (tests_for_{function_name}.c) that thoroughly tests ONLY this specific function, using the Unity Testing Framework.

    CONTEXT:
    - The original main() function has been removed from the coreutils program source.
    - Your tests_for_{function_name}.c file has been directly included into the program source (e.g., via #include "../tests/tests_for_{function_name}.c").
    - All internal functions from the program are accessible.
    - Ensure the test file does not break compilation: do not redefine or redeclare any global symbols, macros, constants, or inline helpers from the original program or its headers.

    REQUIRED FORMAT for `tests.c`: A Unity test file that thoroughly tests the given function's functionality.
    - At the top of the file, add 
        ```c
        #include "../../unity/unity.h"
        ```
        Also include any other standard headers needed for the test code itself(e.g., stdlib.h, string.h, math.h).
    - Implement setUp() and tearDown() functions for Unity:
        ```c
        void setUp(void) {
        /* Setup code here, or leave empty */
        }
        void tearDown(void) {
        /* Cleanup code here, or leave empty */
        }
        ```
    - Create multiple test functions: void test_<function_name>_xxx(void) { ... }. Each test function should set up the necessary preconditions, call the target function, and use Unity assertions to verify expected outcomes.
    - Define main() that calls UNITY_BEGIN(), RUN_TEST() for each test, and returns UNITY_END().
    - CRITICAL RULES FOR STDOUT/STDERR REDIRECTION: Unity's TEST_ASSERT macros write to stdout. If your test redirects stdout (common for I/O testing), Do NOT use TEST_ASSERT macros while stdout is redirected. Use simple if-checks with return NULL for errors. Only use TEST_ASSERT before redirection or after restoration.
    """
    program_name : str = dspy.InputField(description="The coreutils program name (e.g., 'cat')")
    program_code: str = dspy.InputField(description="The full coreutils program code")
    target_function_name: str = dspy.InputField(description="Name of the specific function to test")
    tests_c: str = dspy.OutputField(description="Complete Unity test file that thoroughly tests ONLY the target function")

def initialize_llm():
    """
    Initialize the LLM once and return the configured converter.
    This should be called once at the start of the program.
    """
    print("Initializing LLM...")
    lm = dspy.LM(
        "gpt-5",
        model_type="chat",
        temperature=1.0,
        max_tokens=16000,  # these are required by gpt5
    )
    dspy.configure(lm=lm)
    converter = dspy.ChainOfThought(FunctionToUnityTests)
    print("  ✓ LLM initialized successfully")
    return converter

def generate_unity_tests_with_llm(converter, program_name, program_code, target_function_name):
    """
    Generate Unity tests using a pre-initialized LLM converter.
    
    Args:
        converter: Pre-initialized dspy.ChainOfThought(FunctionToUnityTests) instance
        program_name: The coreutils program name
        program_code: The coreutils program code (e.g., "cat.c")
        target_function_name: Name of the specific function to test
    Returns:
        String containing the generated C code, or False on failure
    """
    try:
        print(f"  Generating tests for {target_function_name}...")
        
        # Generate the Unity tests
        result = converter(
            program_name=program_name,
            program_code=program_code,
            target_function_name=target_function_name
        )

        print(f"  ✓ LLM generation completed for {target_function_name}")
        
        # Extract the generated tests.c code
        tests_c = result.tests_c.strip()
        
        # Check if generation failed (empty string)
        if not tests_c:
            print(f"  ✗ LLM returned empty tests for {target_function_name}")
            return False
        
        # Remove markdown code blocks if present
        if "```c" in tests_c:
            tests_c = tests_c.split("```c")[1].split("```")[0]
        elif "```" in tests_c:
            tests_c = tests_c.split("```")[1].split("```")[0]
        
        return tests_c.strip()
        
    except Exception as e:
        print(f"  ✗ Error generating tests with LLM for {target_function_name}: {e}")
        return False



def remove_main_with_treesitter(c_file, parser):
    """Use tree-sitter to remove main() function from C file"""
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
        
        print(f"  ✓ Removed main() from {c_file}")
        return new_source
    else:
        print(f"  ⚠ No main() found in {c_file}")
        return source_code

def append_include_line_to_code(code_without_main, include_line):
    """Return new code string with include_line appended if absent."""
    lines = code_without_main.splitlines()
    if include_line in lines:
        return '\n'.join(lines) + '\n'  # unchanged (but normalized newline)
    lines.append(include_line)
    return '\n'.join(lines) + '\n'

def extract_program_name(c_file):
    """Extract program name from .c file (e.g., cat.c -> cat)"""
    return Path(c_file).stem


def generate_tests_for_one_coreutils_program(program_name):
    C_LANGUAGE = Language(tsc.language())
    parser = Parser(C_LANGUAGE)
    print(f"Generating Unity tests for {program_name}...")

    src_c_path = os.path.join(HOST_COREUTILS_PATH, 'src', f"{program_name}.c")
    tests_dir_path = os.path.join(HOST_COREUTILS_PATH, 'tests', program_name)
    
    # Check that the source file exists
    if not os.path.exists(src_c_path):
        raise FileNotFoundError(f"Required source file does not exist: {src_c_path}")

    # Check that the tests directory exists
    if not os.path.exists(tests_dir_path):
        os.makedirs(tests_dir_path, exist_ok=True)
        print(f"Required tests directory does not exist: {tests_dir_path}. Making the directory.")
    
    injectable_json_path = os.path.join(INJECTABLE_FUNCTION_PATH, f"{program_name}_injectable_functions.json")

    with open(src_c_path, 'r') as f:
        original_code = f.read()

    code_without_main = remove_main_with_treesitter(src_c_path, parser).decode('utf-8')
    function_info = get_function_info(src_c_path, parser)

    # Initialize LLM once for all functions
    print("\n" + "="*60)
    print("INITIALIZATION")
    print("="*60)
    converter = initialize_llm()

    print("\n" + "="*60)
    print(f"GENERATING TESTS FOR {len(function_info)} FUNCTIONS")
    print("="*60)
    
    injectable_functions = []

    for i, func in enumerate(function_info, 1):
        function_name = func['name']
        function_name_clean = re.sub(r'[^0-9a-zA-Z_]', '_', function_name)
        function_signature = func['signature']
        include_line = f'#include "../tests/{program_name}/tests_for_{function_name_clean}.c"'

        print(f"\n[{i}/{len(function_info)}] Processing function: {function_name}")
        
        injectable_functions.append({
            "function_name": function_name,
            "function_signature": function_signature,
            "include_line": include_line
        })

        code_with_test_include = append_include_line_to_code(code_without_main, include_line)
        
        # Reuse the same converter for all functions
        tests_c_result = generate_unity_tests_with_llm(
            converter,
            program_name, 
            code_with_test_include, 
            function_signature
        )

        # Write test file for this function
        tests_c_per_function_path = os.path.join(tests_dir_path, f"tests_for_{function_name_clean}.c")
        if tests_c_result:
            print(f"  ✓ Writing generated tests to {tests_c_per_function_path}")
            with open(tests_c_per_function_path, "w") as f:
                f.write(tests_c_result)
        else:
            print(f"  ✗ Failed to generate tests for function: {function_name}")

    # Save injectable functions metadata
    print(f"\n  Writing injectable functions metadata to {injectable_json_path}")
    with open(injectable_json_path, "w") as f:
        json.dump(injectable_functions, f, indent=2)

    print("\n" + "="*60)
    print("COMPLETE")
    print("="*60)
    print(f"Generated tests for {len(injectable_functions)} functions")

if __name__ == "__main__":
    program_name = "pwd"
    generate_tests_for_one_coreutils_program(program_name)