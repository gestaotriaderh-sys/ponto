@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Sistema de Ponto

where python >nul 2>nul
if errorlevel 1 (
    echo Python nao encontrado. Instale em https://www.python.org/downloads/
    echo e marque a opcao "Add Python to PATH" durante a instalacao.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Preparando o programa pela primeira vez, aguarde...
    python -m venv .venv || goto erro
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto erro
)

".venv\Scripts\python.exe" iniciar.py
pause
exit /b 0

:erro
echo.
echo Ocorreu um erro na instalacao. Verifique sua conexao com a internet
echo e tente novamente. Se persistir, apague a pasta .venv e rode de novo.
if exist .venv rmdir /s /q .venv
pause
exit /b 1
