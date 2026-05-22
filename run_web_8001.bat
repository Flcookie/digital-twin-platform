@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set CONFIG_FILE=config.json
echo Streamlit on http://localhost:8502 (default 8501 may be in use)
python -m streamlit run streamlit_app\app.py --server.port 8502
