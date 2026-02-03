# reqget- Requirement Generator v1.0.0

import ast
import argparse
import json
import logging
import os
from pathlib import Path
import pkg_resources
import sys
from typing import Set, Dict, List
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
except ImportError:
    tk = None

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Known package mappings
PACKAGE_MAPPINGS = {
    'bs4': 'beautifulsoup4',
    'BeautifulSoup': 'beautifulsoup4',
    'urlparse': 'urllib.parse',
    'urljoin': 'urllib.parse',
}

# Known transitive dependencies with exact versions
TRANSITIVE_DEPS = {
    'beautifulsoup4': ['soupsieve==2.5', 'chardet==5.2.0', 'charset-normalizer==3.4.2', 'lxml==6.0.0'],
    'aiohttp': ['aiohappyeyeballs==2.6.1', 'aiosignal==1.4.0', 'attrs==25.3.0', 'frozenlist==1.7.0', 'propcache==0.3.2'],
    'cssutils': ['cssselect==1.3.0', 'more-itertools==10.7.0', 'pytest-cov==6.2.1'],
    'validators': ['typing-extensions==4.14.0']
}

def load_blacklist(python_version: str) -> Set[str]:
    """Load non-pip-installable modules from blacklist.json for the given Python version."""
    blacklist_file = Path(__file__).parent / 'blacklist.json'
    try:
        with open(blacklist_file, 'r') as f:
            blacklist_data = json.load(f)
        blacklist = set(blacklist_data.get(python_version, {}).get('non_pip_modules', []))
        logging.debug(f"Loaded {len(blacklist)} non-pip-installable modules for Python {python_version} from {blacklist_file}")
        return blacklist
    except Exception as e:
        logging.error(f"Failed to load blacklist file {blacklist_file}: {e}")
        return set()

def load_conflicts(conflict_file: str) -> Dict:
    """Load conflict data from Knownconflicts.json."""
    try:
        with open(conflict_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load conflicts file {conflict_file}: {e}")
        return {}

def extract_imports(file_path: Path) -> Set[str]:
    """Extract imported module names from a Python file using AST."""
    imports = set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    imports.add(name.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
        logging.debug(f"AST extracted imports from {file_path}: {imports}")
    except Exception as e:
        logging.error(f"Failed to parse {file_path}: {e}")
    return imports

def resolve_package(module: str, file_path: Path, blacklist: Set[str]) -> str:
    """Resolve a module name to its package name, excluding blacklisted and local modules."""
    file_dir = file_path.parent
    if (file_dir / f"{module}.py").exists() or (file_dir / module).is_dir():
        logging.debug(f"Skipping local module {module} in {file_path}")
        return None
    if module.lower() in {m.lower() for m in blacklist}:
        logging.debug(f"Skipping blacklisted module {module}")
        return None
    return PACKAGE_MAPPINGS.get(module, module)

def get_package_version(package: str) -> str:
    """Get the installed version of a package."""
    try:
        version = pkg_resources.get_distribution(package).version
        logging.debug(f"Found version {version} for package {package}")
        return version
    except pkg_resources.DistributionNotFound:
        logging.debug(f"Package {package} not installed")
        return None
    except Exception as e:
        logging.error(f"Error getting version for {package}: {e}")
        return None

def check_conflicts(dependencies: Set[str], conflicts: Dict) -> None:
    """Check for known conflicts in dependencies."""
    conflict_table = conflicts.get('conflict_table', [])
    for conflict in conflict_table:
        packages = set(conflict['packages'])
        if packages & {dep.split('==')[0] for dep in dependencies}:
            logging.warning(f"Potential conflict detected: {conflict['packages']}. Resolution: {conflict['resolution']['suggest']}")

def scan_directory(directory: Path, blacklist: Set[str]) -> List[str]:
    """Scan directory for Python files and return dependencies."""
    dependencies = set()
    logging.info(f"Scanning directory: {directory}")
    
    for file_path in directory.rglob('*.py'):
        logging.info(f"Analyzing {file_path}")
        imports = extract_imports(file_path)
        for module in imports:
            package = resolve_package(module, file_path, blacklist)
            if not package:
                continue
            version = get_package_version(package)
            if version:
                dependencies.add(f"{package}=={version}")
            else:
                logging.debug(f"No version found for {package}, using latest known")
                dependencies.add(package)
            for dep in TRANSITIVE_DEPS.get(package, []):
                if dep not in dependencies:
                    dependencies.add(dep)
    
    return sorted(dependencies)

def generate_requirements(dependencies: List[str], directory: Path, output_file: str = 'requirements.txt') -> bool:
    """Generate requirements.txt file in the specified directory."""
    try:
        output_path = Path(directory) / output_file
        with open(output_path, 'w') as f:
            for dep in dependencies:
                f.write(f"{dep}\n")
        logging.info(f"Generated {output_path} with {len(dependencies)} dependencies")
        return True
    except Exception as e:
        logging.error(f"Failed to write {output_path}: {e}")
        return False

def run_scan(directory: str, output_file: str = 'requirements.txt') -> bool:
    """Run the dependency scan for the given directory."""
    directory_path = Path(directory).resolve()
    if not directory_path.is_dir():
        logging.error(f"Directory {directory} does not exist")
        return False
    
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    blacklist = load_blacklist(python_version)
    conflict_file = Path(__file__).parent / 'Knownconflicts.json'
    conflicts = load_conflicts(conflict_file)
    logging.debug(f"Loaded {len(conflicts.get('conflict_table', []))} conflict entries from {conflict_file}")
    
    dependencies = scan_directory(directory_path, blacklist)
    check_conflicts(dependencies, conflicts)
    return generate_requirements(dependencies, directory_path, output_file)

def main():
    parser = argparse.ArgumentParser(description="Dependency Scanner: Generate requirements.txt from Python project imports.")
    parser.add_argument("directory", nargs='?', help="Directory to scan for Python files")
    parser.add_argument("--output", "-o", default="requirements.txt", help="Output filename for dependencies (default: requirements.txt)")
    args = parser.parse_args()
    
    if not args.directory:
        if tk:
            print("No directory provided, launching GUI...")
            return False
        else:
            parser.print_help()
            sys.exit(1)
    
    if run_scan(args.directory, args.output):
        print(f"Successfully generated {args.output} with {len(scan_directory(Path(args.directory).resolve(), load_blacklist(f'{sys.version_info.major}.{sys.version_info.minor}')))} dependencies in {args.directory}")
    else:
        print(f"Failed to scan directory {args.directory}")
        sys.exit(1)
    return True

if __name__ == '__main__':
    if len(sys.argv) == 1 and not tk:
        print("tkinter not available and no directory provided, please provide a directory path")
        print("Usage: python dep_scanner.py <directory> [-o output_file]")
        sys.exit(1)
    
    if len(sys.argv) == 1 or not main():
        if tk:
            root = tk.Tk()
            root.title("Reqget v1.0 by Leon Priest")
            root.geometry("500x300")
            
            tk.Label(root, text="Requirement.txt Generator", font=("Arial", 16)).pack(pady=10)
            
            tk.Label(root, text="Project Path:").pack()
            dir_entry = tk.Entry(root, width=50)
            dir_entry.pack(pady=5)
            
            tk.Label(root, text="Output Filename:").pack()
            output_entry = tk.Entry(root, width=50)
            output_entry.insert(0, "requirements.txt")
            output_entry.pack(pady=5)
            
            def browse_directory():
                directory = filedialog.askdirectory()
                if directory:
                    dir_entry.delete(0, tk.END)
                    dir_entry.insert(0, directory)
            
            tk.Button(root, text="Browse", command=browse_directory).pack(pady=5)
            
            status_label = tk.Label(root, text="", wraplength=400)
            status_label.pack(pady=10)
            
            def scan():
                directory = dir_entry.get()
                output_file = output_entry.get() or "requirements.txt"
                if not directory:
                    status_label.config(text="Please enter or select a directory", fg="red")
                    return
                try:
                    if run_scan(directory, output_file):
                        status_label.config(text=f"Success: Generated {output_file} in {directory}", fg="green")
                    else:
                        status_label.config(text=f"Error: Directory {directory} does not exist", fg="red")
                except Exception as e:
                    status_label.config(text=f"Error: {str(e)}", fg="red")
                    logging.error(f"Scan failed: {e}")
            
            tk.Button(root, text="Scan Dependencies", command=scan).pack(pady=10)
            tk.Button(root, text="Exit", command=root.quit).pack(pady=5)
            
            root.mainloop()