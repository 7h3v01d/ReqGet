# Reqget: Smart Requirements.txt Generator

**Version**: 1.0.0  
**Author**: Leon Priest

## 🧠 What is Reqget?

Reqget is a smart dependency scanner that traverses a Python codebase to:
- Extract imports using AST
- Map them to pip-installable packages
- Resolve transitive dependencies
- Check for known package conflicts
- Output a `requirements.txt` automatically

Includes optional Tkinter GUI for easier use.

## 🧪 Features
- Accurate import analysis
- Conflict checking via curated `Knownconflicts.json`
- Transitive dependency inclusion
- GUI and CLI interface
- Blacklist-aware (stdlib-safe)

## 🖥️ Usage (CLI)

```bash
python cli.py /path/to/project
To specify an output filename:

bash
Copy
Edit
python cli.py /path/to/project -o myreqs.txt
🪟 GUI Mode
If Tkinter is available and no arguments are passed:

bash
Copy
Edit
python cli.py
📦 Installation (when released)
bash
Copy
Edit
pip install reqget
🔐 License
MIT License – see LICENSE.md

Built with ❤️ by Leon Priest.

yaml
Copy
Edit

---

### ✅ 5. `requirements.txt` (minimal for your project)

```txt
pkg_resources