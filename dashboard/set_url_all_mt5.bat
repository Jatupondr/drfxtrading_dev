@echo off
setlocal enabledelayedexpansion
title DRFX - Set WebRequest URL for ALL MT5 Terminals
color 0B

echo ==================================================
echo   Set WebRequest URL for ALL MT5 Terminals
echo ==================================================
echo.

set "TARGET_URL=http://210.246.215.224:8000"
set COUNT=0

echo Target URL: %TARGET_URL%
echo.
echo Searching for MT5 Terminal configs...
echo.

:: Search all terminal data folders
for /d %%T in ("%APPDATA%\MetaQuotes\Terminal\*") do (
    set "CFG=%%T\config\common.ini"
    if exist "!CFG!" (
        echo [FOUND] %%T
        
        :: Check if URL already exists
        findstr /C:"%TARGET_URL%" "!CFG!" >nul 2>&1
        if !errorlevel! == 0 (
            echo         Already has URL - SKIP
        ) else (
            :: Enable WebRequest and add URL
            echo. >> "!CFG!"
            echo [Experts] >> "!CFG!"
            echo AllowWebRequest=1 >> "!CFG!"
            echo WebRequestUrl=%TARGET_URL% >> "!CFG!"
            echo         URL ADDED!
        )
        set /a COUNT+=1
        echo.
    )
)

:: Also check portable MT5
for %%P in ("C:\MT5-*" "D:\MT5-*" "%USERPROFILE%\Desktop\MT5*" "%USERPROFILE%\Desktop\MetaTrader*" "C:\Program Files\MetaTrader*") do (
    for /d %%T in (%%P) do (
        set "CFG=%%T\config\common.ini"
        if exist "!CFG!" (
            echo [FOUND] %%T
            findstr /C:"%TARGET_URL%" "!CFG!" >nul 2>&1
            if !errorlevel! == 0 (
                echo         Already has URL - SKIP
            ) else (
                echo. >> "!CFG!"
                echo [Experts] >> "!CFG!"
                echo AllowWebRequest=1 >> "!CFG!"
                echo WebRequestUrl=%TARGET_URL% >> "!CFG!"
                echo         URL ADDED!
            )
            set /a COUNT+=1
            echo.
        )
    )
)

echo ==================================================
if !COUNT! == 0 (
    echo   No MT5 Terminals found!
) else (
    echo   DONE! Updated !COUNT! terminals
    echo.
    echo   *** RESTART all MT5 Terminals for changes ***
    echo   *** Then check: Tools - Options - Expert Advisors ***
)
echo ==================================================
echo.
pause
