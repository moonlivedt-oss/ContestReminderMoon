@echo off
rem Сборка native\bin\crnative.exe (C++20, C++/WinRT) компилятором MSVC.
rem Нужны Visual Studio или Build Tools с "Разработка классических приложений на C++"
rem и Windows SDK 10.0.17763+ (в нём заголовки C++/WinRT). Без них программа
rem работает и так - просто без уведомлений Windows и сторожа.
setlocal
cd /d "%~dp0"

rem cl уже в PATH (Developer Command Prompt, CI) - окружение не трогаем
where cl >nul 2>&1
if not errorlevel 1 goto :build
rem Иначе ищем Visual Studio через vswhere. Скобки в %ProgramFiles(x86)% ломают
rem блоки if (...), поэтому дальше только goto.
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto :novs
set "VSDIR="
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSDIR=%%i"
if not defined VSDIR goto :novs
if not exist "%VSDIR%\VC\Auxiliary\Build\vcvars64.bat" goto :novs
call "%VSDIR%\VC\Auxiliary\Build\vcvars64.bat" >nul
goto :build

:novs
echo MSVC not found: install Visual Studio Build Tools with the C++ workload.
exit /b 1

:build
if not exist bin mkdir bin
if not exist obj mkdir obj
cl /nologo /std:c++20 /EHsc /O2 /MT /utf-8 /permissive- /W4 /DUNICODE /D_UNICODE ^
   /Foobj\ crnative.cpp /Fe:bin\crnative.exe ^
   /link /SUBSYSTEM:WINDOWS windowsapp.lib winhttp.lib shell32.lib advapi32.lib user32.lib ole32.lib
if errorlevel 1 exit /b 1
copy /y ..\contestreminder\assets\bell.png bin\icon.png >nul
echo Built: native\bin\crnative.exe
