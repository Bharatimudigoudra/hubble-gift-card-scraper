@echo off
call conda activate GenAI
python -m pip install -r requirements.txt
python hubble_scraper.py --full
pause
