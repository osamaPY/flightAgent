@echo off
title Flight Meet
rem Use UTF-8 so the emoji the bot/CLI print don't crash the Windows console.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
:menu
cls
echo ==============================
echo       FLIGHT MEET v7
echo ==============================
echo.
echo  [1] Start Bot
echo  [2] Search Deals
echo  [3] View Results
echo  [4] System Health
echo  [5] Start API
echo  [6] Kick VPS
echo  [0] Exit
echo.
echo ==============================
set /p choice="> "

if "%choice%"=="1" goto bot
if "%choice%"=="2" goto search
if "%choice%"=="3" goto results
if "%choice%"=="4" goto health
if "%choice%"=="5" goto api
if "%choice%"=="6" goto kick
if "%choice%"=="0" exit
goto menu

:bot
cls
echo Starting bot...
echo The bot handles its own recovery (no need for auto-restart loop).
echo If the bot crashes completely, restart it from this menu.
echo.
python telegram_bot.py
pause
goto menu

:search
cls
echo Searching for deals...
python main.py booking-mode
pause
goto menu

:results
cls
python main.py inspect-db
pause
goto menu

:health
cls
echo Provider check...
python main.py health
echo.
python main.py selftest
pause
goto menu

:api
cls
echo API at http://127.0.0.1:8000
echo Ctrl+C to stop.
python flight_api_server.py
pause
goto menu

:kick
cls
python scripts/kick_vps.py
pause
goto menu
