@echo off
cd /d "%~dp0"
set CONFIG_FILE=config.json
python -m streamlit run streamlit_app\app.py
