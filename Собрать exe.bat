@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem Сборка ContestReminder.exe (один файл, без консоли) через PyInstaller.
rem Python 3.11/3.12 ищется так же, как в Запуск.bat; PyInstaller ставится сам.
set "PY="
for %%V in (3.11 3.12) do if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
)
if not defined PY (
    python -c "import sys; sys.exit(sys.version_info[:2] not in ((3, 11), (3, 12)))" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Нужен Python 3.11 или 3.12. Запустите сначала Запуск.bat - он предложит его поставить.
    pause
    exit /b 1
)
echo === C++: уведомления Windows и сторож ===
call native\build.cmd
if errorlevel 1 echo Без C++-части: exe соберётся, но без уведомлений Windows и сторожа.
echo === Пакеты и PyInstaller ===
%PY% -m pip install --disable-pip-version-check -r requirements.txt pyinstaller || goto :fail
echo === Сборка ===
%PY% -m PyInstaller ContestReminder.spec --noconfirm --clean || goto :fail
echo === Самопроверка ===
dist\ContestReminder.exe --selftest "%TEMP%\contestreminder-selftest.txt"
set "CODE=%errorlevel%"
type "%TEMP%\contestreminder-selftest.txt"
if not "%CODE%"=="0" goto :fail
echo.
echo Готово: dist\ContestReminder.exe
pause
exit /b 0

:fail
echo.
echo Сборка не удалась. Текст ошибки - выше.
pause
exit /b 1
