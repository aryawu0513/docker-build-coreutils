from tree_sitter import Language, Parser
import tree_sitter_c as tsc
from typing import List, Dict, Tuple, Any

def extract_target_functions_from_main(program_code: bytes) -> List[Dict[str, str]]:
    """
    Step 1: Parse main() and extract all functions called within it
    Returns list of {name, signature} for each called function
    """

    C_LANGUAGE = Language(tsc.language())
    parser = Parser(C_LANGUAGE)
    tree = parser.parse(program_code)
    # Find main function
    
    def find_main_function(node):
        if node.type == 'function_definition':
            # Check if this is the main function
            for child in node.children:
                if child.type == 'function_declarator':
                    for subchild in child.children:
                        if subchild.type == 'identifier' and program_code[subchild.start_byte:subchild.end_byte] == b'main':
                            return node
        
        for child in node.children:
            result = find_main_function(child)
            if result:
                return result
        return None

    main_node = find_main_function(tree.root_node)
    if not main_node:
        print("ERROR: Could not find main() function")
        return []
    
    # Extract all function calls in main
    function_calls = set()
    
    def extract_calls(node):
        if node.type == 'call_expression':
            for child in node.children:
                if child.type == 'identifier':
                    func_name = program_code[child.start_byte:child.end_byte].decode('utf-8')
                    function_calls.add(func_name)
                    break
        
        for child in node.children:
            extract_calls(child)
    
    extract_calls(main_node)
    
    # Filter out standard library functions
    stdlib_functions = {
        'printf', 'fprintf', 'sprintf', 'snprintf', 'malloc', 'free', 'realloc',
        'strcmp', 'strcpy', 'strlen', 'memcpy', 'memset', 'exit', 'atexit',
        'setlocale', 'bindtextdomain', 'textdomain', 'fflush', 'raise',
        'hash_initialize', 'hash_free', 'hash_remove', 'hash_get_n_entries',
        'obstack_init', 'tzalloc', 'xmalloc', 'xgethostname', 'xalloc_die',
        'assert_matching_dev_ino', 'affirm', 'assure',  # Debug macros
    }
    
    target_calls = function_calls - stdlib_functions
    
    # Now find the actual function definitions for these calls
    target_functions = []
    
    def find_all_functions(node):
        functions = []
        if node.type == 'function_definition':
            # Get function name
            func_name = None
            for child in node.children:
                if child.type == 'function_declarator':
                    for subchild in child.children:
                        if subchild.type == 'identifier':
                            func_name = program_code[subchild.start_byte:subchild.end_byte].decode('utf-8')
                            break
                    break
            
            if func_name and func_name in target_calls:
                # Extract signature (everything before the opening brace)
                for child in node.children:
                    if child.type == 'compound_statement':
                        sig_end = child.start_byte
                        signature = program_code[node.start_byte:sig_end].decode('utf-8').strip()
                        
                        functions.append({
                            'name': func_name,
                            'signature': signature,
                            'start_byte': node.start_byte,
                            'end_byte': node.end_byte,
                        })
                        break
        
        for child in node.children:
            functions.extend(find_all_functions(child))
        
        return functions
    
    all_program_functions = find_all_functions(tree.root_node)
    
    # Map by name
    func_map = {f['name']: f for f in all_program_functions}
    
    # Get target functions that were actually found
    for call_name in target_calls:
        if call_name in func_map:
            target_functions.append(func_map[call_name])
    
    print(f"\n=== Step 1: Functions Called in main() ===")
    print(f"Found {len(target_functions)} target functions:")
    for func in target_functions:
        print(f"  ⭐ {func['name']}")
    
    return target_functions


def reconstruct_minimal_context(
    program_code: bytes,
    target_function: Dict[str, str],
    all_functions: List[Dict[str, str]],
    max_depth: int = 10
) -> str:
    """
    Step 2: For a target function, extract only what's needed:
    - Type definitions (structs, enums, typedefs) - ONLY USED ONES
    - Global variables
    - Macros
    - Helper functions (recursively up to max_depth)
    - Target function itself
    
    Returns: Reconstructed minimal ls.c
    """
    from tree_sitter import Language, Parser
    import tree_sitter_c as tsc
    
    C_LANGUAGE = Language(tsc.language())
    parser = Parser(C_LANGUAGE)
    tree = parser.parse(program_code)
    
    print(f"\n=== Step 2: Building context for {target_function['name']} ===")
    
    # ===== 2.1: Find Helper Functions FIRST (we need this to filter types) =====
    print("  Finding helper functions...")
    
    # Build function map
    function_map = {f['name']: f for f in all_functions}
    
    # Recursively find dependencies
    needed_helpers = {}  # name -> {depth, function_dict}
    
    def find_dependencies(func_name, current_depth):
        if current_depth > max_depth:
            return
        
        if func_name not in function_map:
            return
        
        # Extract function body to find calls
        func = function_map[func_name]
        func_code = program_code[func['start_byte']:func['end_byte']]
        
        # Parse just this function
        func_tree = parser.parse(func_code)
        
        # Find all calls
        calls = set()
        def extract_calls(node):
            if node.type == 'call_expression':
                for child in node.children:
                    if child.type == 'identifier':
                        call_name = func_code[child.start_byte:child.end_byte].decode('utf-8')
                        calls.add(call_name)
                        break
            for child in node.children:
                extract_calls(child)
        
        extract_calls(func_tree.root_node)
        
        # Add dependencies
        for call_name in calls:
            if call_name in function_map:
                # Track the shallowest depth we've seen this function at
                if call_name not in needed_helpers or needed_helpers[call_name]['depth'] > current_depth:
                    needed_helpers[call_name] = {
                        'depth': current_depth,
                        'function': function_map[call_name]
                    }
                    # Recurse
                    find_dependencies(call_name, current_depth + 1)
    
    # Start from target function
    find_dependencies(target_function['name'], 1)
    
    print(f"    Found: {len(needed_helpers)} helper functions (within depth {max_depth})")
    
    # Sort helpers by depth (closer dependencies first)
    sorted_helpers = sorted(needed_helpers.items(), key=lambda x: x[1]['depth'])
    
    # ===== 2.2: Extract ONLY USED Type Definitions =====
    print("  Extracting type definitions (only used types)...")
    
    # Call the second function to get only used types
    structs, enums, typedefs = extract_used_types(
        program_code,
        tree,
        target_function,
        needed_helpers  # ← Pass the helpers we found
    )
    
    print(f"    Kept: {len(structs)} structs, {len(enums)} enums, {len(typedefs)} typedefs")
    
    # ===== 2.3: Extract Global Variables =====
    print("  Extracting global variables...")
    
    globals_list = []
    
    def extract_globals(node, depth=0):
        # File-scope declarations
        if node.type == 'translation_unit':
            for child in node.children:
                if child.type == 'declaration':
                    code = program_code[child.start_byte:child.end_byte].decode('utf-8')
                    # Exclude function declarations (have parentheses and semicolon)
                    if not ('(' in code and code.rstrip().endswith(';') and '{' not in code):
                        globals_list.append(code)
        
        for child in node.children:
            extract_globals(child, depth + 1)
    
    extract_globals(tree.root_node)
    
    print(f"    Found: {len(globals_list)} global variables")
    
    # ===== 2.4: Extract Macros =====
    print("  Extracting macros...")
    
    macros = []
    lines = program_code.decode('utf-8').split('\n')
    for line in lines:
        if line.strip().startswith('#define'):
            macros.append(line)
    
    print(f"    Found: {len(macros)} macros")
    
    # ===== 2.5: Assemble Reconstructed Context =====
    print("  Assembling minimal context...")
    
    context_parts = []
    
    # Header comment
    context_parts.append(f"""/* =====================================================
 * RECONSTRUCTED MINIMAL CONTEXT FOR: {target_function['name']}
 * Original file: ls.c (~5600 lines)
 * This context: Only what's needed for testing
 * ===================================================== */
""")
    
    # Type definitions
    if structs or enums or typedefs:
        context_parts.append("/* ===== TYPE DEFINITIONS ===== */\n")
        if structs:
            context_parts.append("/* Structs */")
            for struct in structs:
                context_parts.append(struct + "\n")
        if enums:
            context_parts.append("\n/* Enums */")
            for enum in enums:
                context_parts.append(enum + "\n")
        if typedefs:
            context_parts.append("\n/* Typedefs */")
            for typedef in typedefs:
                context_parts.append(typedef + "\n")
    
    # Macros
    if macros:
        context_parts.append("\n/* ===== MACROS AND CONSTANTS ===== */\n")
        context_parts.append('\n'.join(macros[:100]))  # Limit to first 100 macros
    
    # Global variables
    if globals_list:
        context_parts.append("\n/* ===== GLOBAL VARIABLES ===== */\n")
        context_parts.append('\n'.join(globals_list[:50]))  # Limit to first 50 globals
    
    # Helper functions
    if sorted_helpers:
        context_parts.append("\n/* ===== HELPER FUNCTIONS ===== */")
        context_parts.append(f"/* {len(sorted_helpers)} functions needed by {target_function['name']} */\n")
        
        for helper_name, helper_info in sorted_helpers:
            helper_func = helper_info['function']
            depth = helper_info['depth']
            
            # Get full function code
            helper_code = program_code[helper_func['start_byte']:helper_func['end_byte']].decode('utf-8')
            lines = helper_code.count('\n')
            
            # Decide: full code or signature only
            if lines < 50 or depth == 1:  # Include full code for small functions or direct dependencies
                context_parts.append(f"/* {helper_name} - depth {depth}, {lines} lines */")
                context_parts.append(helper_code + "\n")
            else:  # Just signature for large indirect dependencies
                context_parts.append(f"{helper_func['signature']};  /* depth {depth}, {lines} lines */\n")
    
    # Target function
    context_parts.append("\n/* ===== TARGET FUNCTION ===== */")
    target_code = program_code[target_function['start_byte']:target_function['end_byte']].decode('utf-8')
    target_lines = target_code.count('\n')
    context_parts.append(f"/* {target_function['name']} - {target_lines} lines */\n")
    context_parts.append(target_code)
    
    # Assemble
    reconstructed = '\n'.join(context_parts)
    
    original_size = len(program_code)
    reconstructed_size = len(reconstructed)
    reduction = (1 - reconstructed_size / original_size) * 100
    
    print(f"\n  ✅ Context reconstructed:")
    print(f"    Original: {original_size:,} chars")
    print(f"    Reconstructed: {reconstructed_size:,} chars")
    print(f"    Reduction: {reduction:.1f}%")
    print(f"    Helpers included: {len(sorted_helpers)}")
    
    return reconstructed


def extract_used_types(
    program_code: bytes,
    tree,
    target_function: Dict[str, str],
    needed_helpers: Dict[str, Any]
) -> Tuple[List[str], List[str], List[str]]:
    """
    Extract only the structs/enums/typedefs that are actually used
    by the target function and its helpers
    """
    import re
    
    # Collect all functions we care about (target + helpers)
    relevant_functions = [target_function]
    for helper_info in needed_helpers.values():
        relevant_functions.append(helper_info['function'])
    
    # Find which types are referenced in these functions
    referenced_types = set()
    
    for func in relevant_functions:
        func_code = program_code[func['start_byte']:func['end_byte']].decode('utf-8')
        
        # Find struct references: struct fileinfo, struct stat, etc.
        struct_refs = re.findall(r'struct\s+(\w+)', func_code)
        referenced_types.update(struct_refs)
        
        # Find enum references: enum filetype
        enum_refs = re.findall(r'enum\s+(\w+)', func_code)
        referenced_types.update(enum_refs)
        
        # Find typedef references (common types)
        typedef_refs = re.findall(r'\b(idx_t|size_t|off_t|mode_t|time_t|dev_t|ino_t|uintmax_t|pid_t|uid_t|gid_t)\b', func_code)
        referenced_types.update(typedef_refs)
    
    print(f"    Referenced types ({len(referenced_types)}): {', '.join(sorted(list(referenced_types))[:10])}...")
    
    # Now extract only these types
    structs = []
    enums = []
    typedefs = []
    
    def extract_specific_types(node):
        if node.type == 'struct_specifier':
            code = program_code[node.start_byte:node.end_byte].decode('utf-8')
            
            # Extract struct name (could be in different child positions)
            struct_name = None
            for child in node.children:
                if child.type == 'type_identifier':
                    struct_name = program_code[child.start_byte:child.end_byte].decode('utf-8')
                    break
            
            # Also check if struct is used anonymously (check first word after "struct")
            if not struct_name:
                # Try to extract from the code itself
                match = re.search(r'struct\s+(\w+)', code)
                if match:
                    struct_name = match.group(1)
            
            # Only include if referenced
            if struct_name and struct_name in referenced_types:
                if code not in structs:
                    structs.append(code)
                    print(f"      ✓ Including struct {struct_name}")
            elif not struct_name and any(ref in code for ref in referenced_types):
                # Anonymous struct but referenced
                if code not in structs:
                    structs.append(code)
                    print(f"      ✓ Including anonymous struct")
        
        elif node.type == 'enum_specifier':
            code = program_code[node.start_byte:node.end_byte].decode('utf-8')
            
            # Extract enum name
            enum_name = None
            for child in node.children:
                if child.type == 'type_identifier':
                    enum_name = program_code[child.start_byte:child.end_byte].decode('utf-8')
                    break
            
            # Fallback: extract from code
            if not enum_name:
                match = re.search(r'enum\s+(\w+)', code)
                if match:
                    enum_name = match.group(1)
            
            # Only include if referenced
            if enum_name and enum_name in referenced_types:
                if code not in enums:
                    enums.append(code)
                    print(f"      ✓ Including enum {enum_name}")
        
        elif node.type == 'type_definition':
            code = program_code[node.start_byte:node.end_byte].decode('utf-8')
            
            # Check if any referenced type appears in this typedef
            for ref_type in referenced_types:
                if ref_type in code:
                    if code not in typedefs:
                        typedefs.append(code)
                        print(f"      ✓ Including typedef containing {ref_type}")
                    break
        
        for child in node.children:
            extract_specific_types(child)
    
    extract_specific_types(tree.root_node)
    
    return structs, enums, typedefs

if __name__ == "__main__":
    with open("ls.c", "rb") as f:
        program_code = f.read()
    target_functions = extract_target_functions_from_main(program_code)
    for target_func in target_functions:
        context = reconstruct_minimal_context(program_code, target_func, target_functions, max_depth=10)
        output_file = f"reconstructed_{target_func['name']}.c"
        with open(output_file, "w") as out_f:
            out_f.write(context)
        print(f"Reconstructed context for {target_func['name']} written to {output_file}")