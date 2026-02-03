# 📦 ReqGet (Archived)

A small Python utility that **extracts third-party dependencies from source code** by analyzing import statements.

ReqGet is archived and represents an early exploration into static analysis and dependency discovery.

---

## 🚀 What problem does this solve?

Python projects often drift out of sync with their `requirements.txt`.

ReqGet answers a simple question:

> “What packages does this script actually import?”

By inspecting source files directly, ReqGet avoids guesswork and environment-specific noise.

---

## ✨ What it does

- Scans Python files for `import` and `from ... import ...` statements
- Filters out Python standard library modules
- Outputs a list of third-party dependencies
- Works without executing the code

This makes it useful for:
- quick audits
- rebuilding lost `requirements.txt` files
- understanding unfamiliar scripts

---

## ▶️ Usage

```bash
python reqget.py path/to/script.py
```
Output is a simple list of detected dependencies.

## 🧠 Design notes
Uses static analysis instead of runtime inspection

-Avoids environment coupling

- Focuses on clarity over completeness

ReqGet does not:

- resolve versions
- install packages
- manage environments

Those concerns are intentionally left out.

## ⚠️ Limitations
Dynamic imports may not be detected

Does not infer transitive dependencies

Standard library list reflects the Python version at the time

This tool is best used as a starting point, not a full dependency manager.
## 📜 License
Unlicensed (personal archive).

### 🏷️ Status
Archived — small, focused, and correct.
