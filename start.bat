@echo off
rem Starter VITA Udgravningsmodel i browseren (kun på denne pc)
cd /d "%~dp0"
py -m streamlit run app.py --server.address localhost --browser.gatherUsageStats false
if errorlevel 1 pause
