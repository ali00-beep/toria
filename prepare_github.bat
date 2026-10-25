@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo Проверка проекта перед публикацией на GitHub...
echo.

if exist .env (
    echo [OK] .env найден и не должен попасть в Git.
) else (
    echo [INFO] .env отсутствует — для Ollama это нормально.
)

if exist .venv echo [OK] .venv находится в .gitignore.
if exist workspace echo [OK] workspace находится в .gitignore.
if exist logs echo [OK] logs находится в .gitignore.

echo.
echo Проверка потенциальных секретов в отслеживаемых файлах:
git grep -n -I -E "sk-[A-Za-z0-9_-]{20,}" -- . ":(exclude)prepare_github.bat"
set "SECRET_FOUND=%errorlevel%"
git grep -n -I -E "AIza[A-Za-z0-9_-]{20,}" -- . ":(exclude)prepare_github.bat"
if not "%errorlevel%"=="1" set "SECRET_FOUND=0"
git grep -n -I -E "password=[^y]" -- . ":(exclude)prepare_github.bat"
if not "%errorlevel%"=="1" set "SECRET_FOUND=0"
git grep -n -I -E "token=[^y]" -- . ":(exclude)prepare_github.bat"
if not "%errorlevel%"=="1" set "SECRET_FOUND=0"
if "%SECRET_FOUND%"=="1" echo [OK] явные секреты не найдены.

echo.
echo Статус Git:
git status --short
echo.
echo Перед git push проверьте список выше и выполните:
echo   git diff --cached
echo   git push -u origin master
echo.
pause
