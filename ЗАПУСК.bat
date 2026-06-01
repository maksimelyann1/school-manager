@echo off
chcp 65001 >nul
title School Manager Desktop
cd /d "%~dp0"

echo ==============================================
echo        ЗАПУСК SCHOOL MANAGER (DESKTOP)
echo ==============================================
echo.

:: Перевірка наявності віртуального середовища
if not exist "backend\venv\Scripts\python.exe" (
    echo [ПОМИЛКА] Не знайдено середовище: backend\venv\Scripts\python.exe
    echo Переконайтеся, що встановлено всі залежності.
    pause
    exit /b 1
)

:: Автоматична збірка фронтенду якщо є зміни у src/
where npm >nul 2>&1
if %errorlevel% equ 0 (
    echo [1/2] Перевiрка фронтенду...
    set "NEED_BUILD=0"
    if not exist "frontend\dist\index.html" set "NEED_BUILD=1"

    if "%NEED_BUILD%"=="1" (
        echo [1/2] dist не знайдено, збираємо фронтенд...
        cd frontend
        call npm run build
        if %errorlevel% neq 0 (
            echo [ПОМИЛКА] Збiрка фронтенду не вдалася!
            cd ..
            pause
            exit /b 1
        )
        cd ..
        echo [1/2] Фронтенд зiбрано!
    ) else (
        for /f %%i in ('powershell -NoProfile -Command "if ((Get-ChildItem frontend\src -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime -gt (Get-Item frontend\dist\index.html).LastWriteTime) { 1 } else { 0 }"') do set "NEED_BUILD=%%i"
        if "%NEED_BUILD%"=="1" (
            echo [1/2] Знайдено змiни, збираємо фронтенд...
            cd frontend
            call npm run build
            if %errorlevel% neq 0 (
                echo [ПОМИЛКА] Збiрка фронтенду не вдалася!
                cd ..
                pause
                exit /b 1
            )
            cd ..
            echo [1/2] Фронтенд зiбрано!
        ) else (
            echo [1/2] Фронтенд актуальний, збiрка не потрiбна.
        )
    )
) else (
    echo [1/2] npm не знайдено, пропускаємо збiрку.
)

echo.
echo [2/2] Запуск програми...
echo.
"backend\venv\Scripts\python.exe" desktop_app.py

if %errorlevel% neq 0 (
    echo.
    echo [ПОМИЛКА] Програма завершилася з кодом %errorlevel%
    pause
)