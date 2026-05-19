# Reqget: Smart Requirements.txt Generator

**Version**: 1.0.0  
**Author**: Leon Priest

<img width="682" height="652" alt="screenshot" src="https://github.com/user-attachments/assets/1bc2c647-109e-4383-9521-32c71cfe78cf" />


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
