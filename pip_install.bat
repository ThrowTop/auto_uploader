@echo off
setlocal

set PACKAGES=PyQt6 google-api-python-client google-auth-oauthlib google-auth-httplib2 requests pywin32

for %%P in (%PACKAGES%) do (
    py -m pip show %%P >nul 2>&1
    if errorlevel 1 (
        echo Installing %%P...
        py -m pip install %%P
    ) else (
        echo %%P is already installed.
    )
)

echo.
echo All done.
pause
