@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set CONFIG_FILE=config.json
python -m streamlit run streamlit_app\app.py
