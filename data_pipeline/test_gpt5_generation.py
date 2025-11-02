import dspy
import os
from tree_sitter import Language, Parser
import tree_sitter_c as tsc


def get_function_info(c_file, parser):
    """
    Extract detailed information about all functions (except main).
    
    Args:
        c_file: C source file path
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
    You will be given a coreutils program and the name of a SPECIFIC FUNCTION within it to test.
    You should read the coreutils program code and find the code of the target function, and understand its purpose.
    Your task is to write a test suite (tests.c) that thoroughly tests ONLY this specific function, using the Unity Testing Framework.

    IMPORTANT: Your test suite will be evaluated using MUTATION TESTING on ONLY this target function.
    This means:
    - We will inject bugs/mutations into ONLY the target function
    - Your tests must be thorough enough to catch these mutations
    - Focus on edge cases, boundary conditions, and error paths
    - Test different input combinations that exercise all code paths in the function
    
    CONTEXT:
    - The original main() function has been removed from the coreutils program source.
    - Your tests.c file will be directly included into the program source (e.g., via #include "../tests/<program>_tests.c").
    - All internal functions from the program are accessible — no need for extern declarations.
    - Do not redefine or redeclare any global symbols (functions or variables) that already exist in the program or its headers.
    - Use the same headers as the original source file. Do not redefine, #undef, or override any macros, constants, or inline helpers from production headers.

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

    program_code: str = dspy.InputField(description="The full coreutils program code")
    target_function_name: str = dspy.InputField(description="Name of the specific function to test")
    tests_c: str = dspy.OutputField(description="Complete Unity test file that thoroughly tests ONLY the target function")

def generate_unity_tests_with_llm(program_code, target_function_name):
    """
    Args:
        program_code: The coreutils program code (e.g., "cat.c")
        target_function_name: Name of the specific function to test
    Returns:
        String containing the generated C code, or False on failure
    """
    try:
        lm = dspy.LM(
            "gpt-5",
            model_type="chat",
            temperature=1.0,
            max_tokens=16000,#these are required by gpt5
        )
        dspy.configure(lm=lm)

        print("model loaded")
        
        # Use ChainOfThought for better reasoning
        converter = dspy.ChainOfThought(FunctionToUnityTests)
        
        # Generate the Unity tests
        result = converter(
            program_code=program_code,
            target_function_name=target_function_name
        )

        print("LLM generation completed:", result)
        
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
        print(f"  ✗ Error generating tests with LLM: {e}")
        return False

# Example usage
if __name__ == "__main__":
    C_LANGUAGE = Language(tsc.language())
    parser = Parser(C_LANGUAGE)
    print("Generating Unity tests for 'cksum'...")
    file_name = "cksum.c"
    with open(file_name, 'r') as f:
        code_without_main = f.read()
    function_info = get_function_info(file_name, parser)
    for func in function_info:
        function_name = func['name']
        function_signature = func['signature']
        result = generate_unity_tests_with_llm(code_without_main, function_signature)
        result_tests_c_name = f"cksum/tests_for_{function_name.replace(' ','_').replace('(','_').replace(')','')}.c"
        #note, this will need to be included in the program to be compiled and run
        if result:
            os.makedirs(os.path.dirname(result_tests_c_name), exist_ok=True)
            print(f"Writing generated tests to {result_tests_c_name}...")
            with open(result_tests_c_name, "w") as f:
                f.write(result)
        else:
            print("Failed to generate tests for function:", function_name)
    print("Done.")
