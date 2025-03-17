from mcp.server.fastmcp import FastMCP
import os
import subprocess
import json
import glob
import shutil
from typing import Dict, List, Optional, Any, Union
import ast
import re
import logging
import zipfile
import tempfile
from pathlib import Path

# Initialize FastMCP server
mcp = FastMCP("code-assistant")

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DEFAULT_README_PATH = "README.md"

def get_file_content(file_path: str) -> str:
    """Read and return file content."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {str(e)}")
        return f"Error reading file: {str(e)}"

def write_file_content(file_path: str, content: str) -> bool:
    """Write content to a file."""
    try:
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(content)
        return True
    except Exception as e:
        logger.error(f"Error writing to file {file_path}: {str(e)}")
        return False

def execute_command(command: List[str]) -> Dict[str, Any]:
    """Execute a shell command and return the result."""
    try:
        result = subprocess.run(
            command, 
            capture_output=True, 
            text=True, 
            check=False
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        logger.error(f"Error executing command {command}: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def get_project_structure(directory: str) -> Dict[str, Any]:
    """Generate a tree-like structure of the project."""
    def build_tree(path, level=0, is_last=False, prefix=""):
        if os.path.isfile(path):
            return {
                "type": "file",
                "name": os.path.basename(path),
                "path": path,
                "level": level
            }
        
        # It's a directory
        items = os.listdir(path)
        items = [item for item in items if not item.startswith('.') and item != "__pycache__"]
        
        result = {
            "type": "directory",
            "name": os.path.basename(path),
            "path": path,
            "level": level,
            "children": []
        }
        
        for i, item in enumerate(sorted(items)):
            item_path = os.path.join(path, item)
            is_last_item = i == len(items) - 1
            result["children"].append(build_tree(item_path, level + 1, is_last_item))
        
        return result

    try:
        return build_tree(directory)
    except Exception as e:
        logger.error(f"Error generating project structure for {directory}: {str(e)}")
        return {"error": str(e)}

def analyze_python_file(file_path: str) -> Dict[str, Any]:
    """
    Analyze a Python file and return information about its structure.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        tree = ast.parse(content)
        
        # Extract classes and functions
        classes = []
        functions = []
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = []
                for child in node.body:
                    if isinstance(child, ast.FunctionDef):
                        methods.append({
                            "name": child.name,
                            "lineno": child.lineno,
                            "docstring": ast.get_docstring(child) or "No docstring"
                        })
                
                classes.append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "methods": methods,
                    "docstring": ast.get_docstring(node) or "No docstring"
                })
            elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:  # Only top-level functions
                functions.append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "docstring": ast.get_docstring(node) or "No docstring"
                })
            elif isinstance(node, ast.Import):
                for name in node.names:
                    imports.append({"type": "import", "name": name.name})
            elif isinstance(node, ast.ImportFrom):
                for name in node.names:
                    imports.append({"type": "from", "module": node.module, "name": name.name})
        
        # Count lines and docstrings
        line_count = len(content.splitlines())
        docstring_count = sum(1 for node in ast.walk(tree) if 
                               isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)) and 
                               ast.get_docstring(node))
        
        # Calculate docstring coverage
        nodes_requiring_docstrings = sum(1 for node in ast.walk(tree) if 
                                         isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)))
        
        docstring_coverage = 0
        if nodes_requiring_docstrings > 0:
            docstring_coverage = (docstring_count / nodes_requiring_docstrings) * 100
        
        return {
            "file_path": file_path,
            "line_count": line_count,
            "classes": classes,
            "functions": functions,
            "imports": imports,
            "docstring_coverage": docstring_coverage,
            "nodes_requiring_docstrings": nodes_requiring_docstrings,
            "docstring_count": docstring_count
        }
    except Exception as e:
        logger.error(f"Error analyzing Python file {file_path}: {str(e)}")
        return {"error": str(e), "file_path": file_path}

@mcp.tool()
async def list_files(directory: str, pattern: str = "*.py") -> str:
    """
    List files in a directory matching a pattern.
    
    Args:
        directory: The directory to search in
        pattern: File pattern to match (default: "*.py")
    
    Returns:
        A JSON string containing the list of files
    """
    try:
        if not os.path.isdir(directory):
            return json.dumps({"error": f"Directory not found: {directory}"})
        
        files = glob.glob(os.path.join(directory, pattern), recursive=True)
        return json.dumps({"files": files})
    except Exception as e:
        logger.error(f"Error listing files: {str(e)}")
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_file(file_path: str) -> str:
    """
    Get the content of a file.
    
    Args:
        file_path: Path to the file
    
    Returns:
        The file content
    """
    return get_file_content(file_path)

@mcp.tool()
async def update_file(file_path: str, content: str) -> str:
    """
    Update the content of a file.
    
    Args:
        file_path: Path to the file
        content: New content of the file
    
    Returns:
        Success message or error
    """
    success = write_file_content(file_path, content)
    if success:
        return json.dumps({"success": True, "message": f"File {file_path} updated successfully"})
    else:
        return json.dumps({"success": False, "message": f"Failed to update file {file_path}"})

@mcp.tool()
async def analyze_code(file_path: str) -> str:
    """
    Analyze a Python file and return information about its structure.
    
    Args:
        file_path: Path to the Python file
    
    Returns:
        JSON string with code analysis results
    """
    if not file_path.endswith('.py'):
        return json.dumps({"error": "Only Python files are supported for analysis"})
    
    analysis = analyze_python_file(file_path)
    return json.dumps(analysis)

@mcp.tool()
async def generate_docstring(file_path: str, object_name: str = None, line_number: int = None) -> str:
    """
    Generate a docstring for a Python function, class, or module.
    
    Args:
        file_path: Path to the Python file
        object_name: Name of the function or class (optional)
        line_number: Line number of the function or class (optional)
    
    Returns:
        Suggested docstring
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
            
        tree = ast.parse(content)
        target_node = None
        
        # Find the target node
        if object_name:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == object_name:
                    target_node = node
                    break
        elif line_number:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.lineno == line_number:
                    target_node = node
                    break
        else:
            # No specific target, look for nodes without docstrings
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)) and not ast.get_docstring(node):
                    if isinstance(node, ast.Module):
                        target_node = node
                        break
                    elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        target_node = node
                        break
        
        if target_node is None:
            return json.dumps({
                "success": False, 
                "message": "No suitable target found for docstring generation"
            })
        
        # Generate docstring based on node type
        if isinstance(target_node, ast.FunctionDef):
            args = [arg.arg for arg in target_node.args.args if arg.arg != 'self']
            
            docstring = f'"""\n{target_node.name}\n\n'
            
            if args:
                docstring += "Args:\n"
                for arg in args:
                    docstring += f"    {arg}: Description of {arg}\n"
            
            docstring += '\nReturns:\n    Description of return value\n"""'
            
            return json.dumps({
                "success": True,
                "node_type": "function", 
                "name": target_node.name,
                "suggested_docstring": docstring,
                "line_number": target_node.lineno
            })
        
        elif isinstance(target_node, ast.ClassDef):
            docstring = f'"""\n{target_node.name} class\n\nDescription of the class and its purpose.\n"""'
            
            return json.dumps({
                "success": True,
                "node_type": "class", 
                "name": target_node.name,
                "suggested_docstring": docstring,
                "line_number": target_node.lineno
            })
        
        elif isinstance(target_node, ast.Module):
            docstring = f'"""\n{os.path.basename(file_path)}\n\nDescription of the module and its purpose.\n"""'
            
            return json.dumps({
                "success": True,
                "node_type": "module",
                "suggested_docstring": docstring,
                "line_number": 1
            })
        
        return json.dumps({
            "success": False, 
            "message": "Unsupported node type for docstring generation"
        })
    
    except Exception as e:
        logger.error(f"Error generating docstring: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def get_project_tree(directory: str) -> str:
    """
    Get the tree structure of a project directory.
    
    Args:
        directory: Project directory path
    
    Returns:
        JSON string representing the project structure
    """
    if not os.path.isdir(directory):
        return json.dumps({"error": f"Directory not found: {directory}"})
    
    structure = get_project_structure(directory)
    return json.dumps(structure)

@mcp.tool()
async def run_tests(directory: str, pattern: str = "test_*.py") -> str:
    """
    Run Python tests in the specified directory.
    
    Args:
        directory: Directory containing tests
        pattern: Test file pattern (default: "test_*.py")
    
    Returns:
        Test results
    """
    try:
        if not os.path.isdir(directory):
            return json.dumps({"error": f"Directory not found: {directory}"})
        
        # Use pytest to run tests
        result = execute_command(["pytest", directory, "-v"])
        
        return json.dumps({
            "success": result["success"],
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "returncode": result.get("returncode", 1)
        })
    except Exception as e:
        logger.error(f"Error running tests: {str(e)}")
        return json.dumps({"error": str(e)})

@mcp.tool()
async def lint_code(file_path: str) -> str:
    """
    Lint a Python file using flake8.
    
    Args:
        file_path: Path to the Python file
    
    Returns:
        Linting results
    """
    try:
        if not file_path.endswith('.py'):
            return json.dumps({"error": "Only Python files are supported for linting"})
        
        if not os.path.isfile(file_path):
            return json.dumps({"error": f"File not found: {file_path}"})
        
        # Use flake8 to lint the file
        result = execute_command(["flake8", file_path])
        
        return json.dumps({
            "success": result["success"],
            "output": result.get("stdout", ""),
            "errors": result.get("stderr", ""),
            "returncode": result.get("returncode", 1)
        })
    except Exception as e:
        logger.error(f"Error linting code: {str(e)}")
        return json.dumps({"error": str(e)})

@mcp.tool()
async def create_directory(path: str) -> str:
    """
    Create a new directory.
    
    Args:
        path: Path of the directory to create
    
    Returns:
        Result of the operation
    """
    try:
        os.makedirs(path, exist_ok=True)
        return json.dumps({
            "success": True,
            "message": f"Directory created at {path}",
            "path": path
        })
    except Exception as e:
        logger.error(f"Error creating directory: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def delete_file(path: str) -> str:
    """
    Delete a file.
    
    Args:
        path: Path to the file to delete
    
    Returns:
        Result of the operation
    """
    try:
        if not os.path.exists(path):
            return json.dumps({"success": False, "error": f"File not found: {path}"})
        
        if os.path.isdir(path):
            return json.dumps({"success": False, "error": f"Path is a directory, use delete_directory instead: {path}"})
        
        os.remove(path)
        return json.dumps({
            "success": True,
            "message": f"File deleted: {path}"
        })
    except Exception as e:
        logger.error(f"Error deleting file: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def delete_directory(path: str, recursive: bool = False) -> str:
    """
    Delete a directory.
    
    Args:
        path: Path to the directory to delete
        recursive: Whether to delete recursively (default: False)
    
    Returns:
        Result of the operation
    """
    try:
        if not os.path.exists(path):
            return json.dumps({"success": False, "error": f"Directory not found: {path}"})
        
        if not os.path.isdir(path):
            return json.dumps({"success": False, "error": f"Path is not a directory: {path}"})
        
        if recursive:
            shutil.rmtree(path)
        else:
            os.rmdir(path)
        
        return json.dumps({
            "success": True,
            "message": f"Directory deleted: {path}"
        })
    except Exception as e:
        logger.error(f"Error deleting directory: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def copy_file(source: str, destination: str) -> str:
    """
    Copy a file from source to destination.
    
    Args:
        source: Source file path
        destination: Destination file path
    
    Returns:
        Result of the operation
    """
    try:
        if not os.path.exists(source):
            return json.dumps({"success": False, "error": f"Source file not found: {source}"})
        
        if os.path.isdir(source):
            return json.dumps({"success": False, "error": f"Source is a directory, use copy_directory instead: {source}"})
        
        # Create destination directory if it doesn't exist
        dest_dir = os.path.dirname(destination)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        
        shutil.copy2(source, destination)
        return json.dumps({
            "success": True,
            "message": f"File copied from {source} to {destination}",
            "source": source,
            "destination": destination
        })
    except Exception as e:
        logger.error(f"Error copying file: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def copy_directory(source: str, destination: str) -> str:
    """
    Copy a directory from source to destination.
    
    Args:
        source: Source directory path
        destination: Destination directory path
    
    Returns:
        Result of the operation
    """
    try:
        if not os.path.exists(source):
            return json.dumps({"success": False, "error": f"Source directory not found: {source}"})
        
        if not os.path.isdir(source):
            return json.dumps({"success": False, "error": f"Source is not a directory: {source}"})
        
        # Create parent directories if they don't exist
        if not os.path.exists(os.path.dirname(destination)):
            os.makedirs(os.path.dirname(destination), exist_ok=True)
        
        shutil.copytree(source, destination)
        return json.dumps({
            "success": True,
            "message": f"Directory copied from {source} to {destination}",
            "source": source,
            "destination": destination
        })
    except Exception as e:
        logger.error(f"Error copying directory: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def move_file(source: str, destination: str) -> str:
    """
    Move a file from source to destination.
    
    Args:
        source: Source file path
        destination: Destination file path
    
    Returns:
        Result of the operation
    """
    try:
        if not os.path.exists(source):
            return json.dumps({"success": False, "error": f"Source file not found: {source}"})
        
        if os.path.isdir(source):
            return json.dumps({"success": False, "error": f"Source is a directory, use move_directory instead: {source}"})
        
        # Create destination directory if it doesn't exist
        dest_dir = os.path.dirname(destination)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        
        shutil.move(source, destination)
        return json.dumps({
            "success": True,
            "message": f"File moved from {source} to {destination}",
            "source": source,
            "destination": destination
        })
    except Exception as e:
        logger.error(f"Error moving file: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def move_directory(source: str, destination: str) -> str:
    """
    Move a directory from source to destination.
    
    Args:
        source: Source directory path
        destination: Destination directory path
    
    Returns:
        Result of the operation
    """
    try:
        if not os.path.exists(source):
            return json.dumps({"success": False, "error": f"Source directory not found: {source}"})
        
        if not os.path.isdir(source):
            return json.dumps({"success": False, "error": f"Source is not a directory: {source}"})
        
        # Create parent directories if they don't exist
        parent_dir = os.path.dirname(destination)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        shutil.move(source, destination)
        return json.dumps({
            "success": True,
            "message": f"Directory moved from {source} to {destination}",
            "source": source,
            "destination": destination
        })
    except Exception as e:
        logger.error(f"Error moving directory: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def rename_file(source: str, new_name: str) -> str:
    """
    Rename a file.
    
    Args:
        source: Source file path
        new_name: New file name (not path)
    
    Returns:
        Result of the operation
    """
    try:
        if not os.path.exists(source):
            return json.dumps({"success": False, "error": f"Source file not found: {source}"})
        
        if os.path.isdir(source):
            return json.dumps({"success": False, "error": f"Source is a directory, use rename_directory instead: {source}"})
        
        directory = os.path.dirname(source)
        destination = os.path.join(directory, new_name)
        
        os.rename(source, destination)
        return json.dumps({
            "success": True,
            "message": f"File renamed from {source} to {destination}",
            "old_path": source,
            "new_path": destination
        })
    except Exception as e:
        logger.error(f"Error renaming file: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def rename_directory(source: str, new_name: str) -> str:
    """
    Rename a directory.
    
    Args:
        source: Source directory path
        new_name: New directory name (not path)
    
    Returns:
        Result of the operation
    """
    try:
        if not os.path.exists(source):
            return json.dumps({"success": False, "error": f"Source directory not found: {source}"})
        
        if not os.path.isdir(source):
            return json.dumps({"success": False, "error": f"Source is not a directory: {source}"})
        
        parent_dir = os.path.dirname(source)
        destination = os.path.join(parent_dir, new_name)
        
        os.rename(source, destination)
        return json.dumps({
            "success": True,
            "message": f"Directory renamed from {source} to {destination}",
            "old_path": source,
            "new_path": destination
        })
    except Exception as e:
        logger.error(f"Error renaming directory: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def get_file_info(path: str) -> str:
    """
    Get information about a file.
    
    Args:
        path: Path to the file
    
    Returns:
        File information
    """
    try:
        if not os.path.exists(path):
            return json.dumps({"success": False, "error": f"File not found: {path}"})
        
        stats = os.stat(path)
        info = {
            "path": path,
            "size": stats.st_size,
            "last_modified": stats.st_mtime,
            "created": stats.st_ctime,
            "is_directory": os.path.isdir(path),
            "permissions": oct(stats.st_mode)[-3:],
            "exists": True
        }
        
        # Add file extension if it's a file
        if not os.path.isdir(path):
            info["extension"] = os.path.splitext(path)[1]
        
        return json.dumps({"success": True, "info": info})
    except Exception as e:
        logger.error(f"Error getting file info: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def search_in_files(directory: str, pattern: str, file_pattern: str = "*.py") -> str:
    """
    Search for a pattern in files.
    
    Args:
        directory: Directory to search in
        pattern: Regular expression pattern to search for
        file_pattern: File pattern to match (default: "*.py")
    
    Returns:
        Search results
    """
    try:
        if not os.path.isdir(directory):
            return json.dumps({"success": False, "error": f"Directory not found: {directory}"})
        
        results = []
        for root, _, files in os.walk(directory):
            for file in files:
                if not glob.fnmatch.fnmatch(file, file_pattern):
                    continue
                
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    matches = []
                    lines = content.splitlines()
                    for i, line in enumerate(lines):
                        if re.search(pattern, line):
                            matches.append({
                                "line_number": i + 1,
                                "line": line
                            })
                    
                    if matches:
                        results.append({
                            "file": file_path,
                            "matches": matches
                        })
                except Exception as e:
                    logger.warning(f"Error reading file {file_path}: {str(e)}")
        
        return json.dumps({
            "success": True,
            "pattern": pattern,
            "file_pattern": file_pattern,
            "results": results,
            "count": sum(len(r["matches"]) for r in results)
        })
    except Exception as e:
        logger.error(f"Error searching in files: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def find_files(directory: str, pattern: str, recursive: bool = True) -> str:
    """
    Find files matching a pattern.
    
    Args:
        directory: Directory to search in
        pattern: File pattern to match (glob pattern)
        recursive: Whether to search recursively (default: True)
    
    Returns:
        List of matching files
    """
    try:
        if not os.path.isdir(directory):
            return json.dumps({"success": False, "error": f"Directory not found: {directory}"})
        
        if recursive:
            matches = glob.glob(os.path.join(directory, "**", pattern), recursive=True)
        else:
            matches = glob.glob(os.path.join(directory, pattern), recursive=False)
        
        # Convert to relative paths for better readability
        relative_matches = [os.path.relpath(match, directory) for match in matches]
        
        return json.dumps({
            "success": True,
            "pattern": pattern,
            "recursive": recursive,
            "matches": matches,
            "relative_matches": relative_matches,
            "count": len(matches)
        })
    except Exception as e:
        logger.error(f"Error finding files: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def create_file(file_path: str, content: str = "") -> str:
    """
    Create a new file with optional content.
    
    Args:
        file_path: Path to the file to create
        content: Optional content to write to the file
    
    Returns:
        Result of the operation
    """
    try:
        # Create directory if it doesn't exist
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        
        # Check if file already exists
        file_exists = os.path.exists(file_path)
        
        # Write content to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return json.dumps({
            "success": True,
            "message": f"File {'overwritten' if file_exists else 'created'} at {file_path}",
            "path": file_path,
            "existed_before": file_exists
        })
    except Exception as e:
        logger.error(f"Error creating file: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def zip_directory(directory: str, output_path: str = None) -> str:
    """
    Create a zip archive of a directory.
    
    Args:
        directory: Directory to zip
        output_path: Output zip file path (optional)
    
    Returns:
        Result of the operation
    """
    try:
        if not os.path.isdir(directory):
            return json.dumps({"success": False, "error": f"Directory not found: {directory}"})
        
        # If output path is not specified, create it in the parent directory
        if not output_path:
            parent_dir = os.path.dirname(directory)
            dir_name = os.path.basename(directory)
            output_path = os.path.join(parent_dir, f"{dir_name}.zip")
        
        # Create parent directories if they don't exist
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        base_dir = os.path.basename(directory)
        root_dir = os.path.dirname(directory)
        
        shutil.make_archive(
            os.path.splitext(output_path)[0],  # Strip extension if provided
            'zip',
            root_dir,
            base_dir
        )
        
        # Just in case make_archive didn't output to exactly output_path
        actual_output = f"{os.path.splitext(output_path)[0]}.zip"
        
        return json.dumps({
            "success": True,
            "message": f"Directory {directory} zipped to {actual_output}",
            "source_directory": directory,
            "zip_file": actual_output
        })
    except Exception as e:
        logger.error(f"Error zipping directory: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def unzip_file(zip_path: str, extract_to: str = None) -> str:
    """
    Extract a zip archive.
    
    Args:
        zip_path: Path to the zip file
        extract_to: Directory to extract to (optional)
    
    Returns:
        Result of the operation
    """
    try:
        if not os.path.exists(zip_path):
            return json.dumps({"success": False, "error": f"Zip file not found: {zip_path}"})
        
        if not zipfile.is_zipfile(zip_path):
            return json.dumps({"success": False, "error": f"Not a valid zip file: {zip_path}"})
        
        # If extract_to is not specified, extract to the same directory as the zip file
        if not extract_to:
            extract_to = os.path.dirname(zip_path)
        
        # Create extract directory if it doesn't exist
        if not os.path.exists(extract_to):
            os.makedirs(extract_to, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        
        # List extracted top-level files/directories
        extracted_items = [os.path.join(extract_to, item) for item in os.listdir(extract_to)]
        
        return json.dumps({
            "success": True,
            "message": f"Zip file {zip_path} extracted to {extract_to}",
            "zip_file": zip_path,
            "extract_directory": extract_to,
            "extracted_items": extracted_items
        })
    except Exception as e:
        logger.error(f"Error extracting zip file: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def create_temp_directory() -> str:
    """
    Create a temporary directory.
    
    Returns:
        Path to the temporary directory
    """
    try:
        temp_dir = tempfile.mkdtemp()
        return json.dumps({
            "success": True,
            "message": f"Temporary directory created at {temp_dir}",
            "path": temp_dir
        })
    except Exception as e:
        logger.error(f"Error creating temporary directory: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def create_temp_file(suffix: str = None, prefix: str = None, directory: str = None) -> str:
    """
    Create a temporary file.
    
    Args:
        suffix: File suffix (optional)
        prefix: File prefix (optional)
        directory: Directory to create the file in (optional)
    
    Returns:
        Path to the temporary file
    """
    try:
        fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=directory)
        os.close(fd)  # Close the file descriptor
        
        return json.dumps({
            "success": True,
            "message": f"Temporary file created at {path}",
            "path": path
        })
    except Exception as e:
        logger.error(f"Error creating temporary file: {str(e)}")
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def update_readme(project_dir: str, sections: Optional[List[str]] = None) -> str:
    """
    Update the README.md file with project information.
    
    Args:
        project_dir: Project directory path
        sections: List of sections to update (optional)
    
    Returns:
        Result of the README update
    """
    try:
        if not os.path.isdir(project_dir):
            return json.dumps({"error": f"Directory not found: {project_dir}"})
        
        readme_path = os.path.join(project_dir, DEFAULT_README_PATH)
        readme_exists = os.path.isfile(readme_path)
        
        # Read current README if it exists
        current_content = ""
        if readme_exists:
            current_content = get_file_content(readme_path)
        
        # Generate new content or update sections
        if not readme_exists or not current_content:
            # Generate a new README
            project_name = os.path.basename(os.path.abspath(project_dir))
            new_content = f"# {project_name}\n\n"
            new_content += "## Description\n\nProject description here.\n\n"
            new_content += "## Installation\n\n```bash\npip install -r requirements.txt\n```\n\n"
            new_content += "## Usage\n\nUsage instructions here.\n\n"
            new_content += "## License\n\n[MIT](https://choosealicense.com/licenses/mit/)\n"
        else:
            # Update specific sections if requested
            new_content = current_content
            if sections:
                # For now, we'll just append a note that these sections should be updated
                new_content += "\n\n## Updates Needed\n\n"
                new_content += "The following sections need to be updated:\n\n"
                for section in sections:
                    new_content += f"- {section}\n"
        
        # Write the updated README
        success = write_file_content(readme_path, new_content)
        
        if success:
            return json.dumps({
                "success": True,
                "message": "README updated successfully",
                "created_new": not readme_exists,
                "path": readme_path
            })
        else:
            return json.dumps({
                "success": False,
                "message": "Failed to update README"
            })
    except Exception as e:
        logger.error(f"Error updating README: {str(e)}")
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    mcp.run(transport='stdio')
