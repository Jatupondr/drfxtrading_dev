@echo off
cd /d C:\inetpub\wwwroot\drfxtrading.net\dashboard
call venv\Scripts\activate
cd backend
python main.py
pause