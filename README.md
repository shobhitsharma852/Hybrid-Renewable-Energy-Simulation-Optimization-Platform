# Hybrid Renewable Energy Optimization Engine

A simulation and optimization engine for hybrid microgrids (PV + Wind + Battery + Grid),
with a Streamlit dashboard for building projects, running simulations, and optimizing designs.

---

## Requirements

- Python 3.13 (the project's virtual environment uses 3.13.6)
- The dependencies listed in [`requirements.txt`](requirements.txt)

## One-time setup

From the project root (`hybrid_homer_engine`), create the virtual environment and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> The project ships a `.pth` file in the venv (`insolare_project_root.pth`) that puts the
> project root on Python's path, so `dashboard` and `core` import correctly no matter which
> folder you launch from. If you recreate the venv, add it back with:
> ```powershell
> Add-Content .venv\Lib\site-packages\insolare_project_root.pth "$(Get-Location)"
> ```

---

## How to start the dashboard

From the project root, run the **venv's** Streamlit:

```powershell
.venv\Scripts\streamlit.exe run dashboard/app.py
```

Then open the URL it prints (default: http://localhost:8501).

### Why this exact command

- **Use `.venv\Scripts\streamlit.exe`, not `py -m streamlit`.** On this machine `py` defaults to a
  separate Python 3.14 (installed by PyManager) that does **not** have `scipy` — so `py -m streamlit`
  fails on the Optimization page with `No module named 'scipy'`. The venv's Streamlit always uses the
  Python that has every dependency.
- **No `PYTHONPATH` or activation needed.** The `.pth` file handles the `dashboard` / `core` imports.

### If you prefer VS Code

Open the project in VS Code, select the `.venv` (3.13.6) interpreter (bottom-right), and use the
**integrated terminal** — it auto-activates the venv and sets the path, so `py -m streamlit run
dashboard/app.py` also works there.

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `No module named 'scipy'` | Running on the 3.14 Python (via `py`) which lacks scipy | Use `.venv\Scripts\streamlit.exe run dashboard/app.py` |
| `No module named 'dashboard'` / `'core'` | Project root not on Python's path | Run from the project root; the venv `.pth` normally handles this |
| `Activate.ps1 cannot be loaded ... scripts is disabled` | PowerShell execution policy | You don't need to activate — use the `.venv\Scripts\streamlit.exe` command. (Or run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`) |

---

## Project layout

```
core/          simulation, optimization, and component models (the engine)
dashboard/     Streamlit UI (app.py + pages/)
projects/      saved projects (inputs, components, outputs)
tests/         validation and HOMER-comparison tests
docs/          design and alignment notes
```
