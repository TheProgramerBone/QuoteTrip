@echo off
REM ============================================================
REM  Genera el instalador QuoteTrip-Setup.exe
REM  Paso 1: compila la app con PyInstaller (SIEMPRE, no solo si
REM          falta dist\QuoteTrip — antes se saltaba este paso
REM          si ya existia un build viejo de una sesion anterior,
REM          y el instalador terminaba empaquetando codigo
REM          desactualizado con la version nueva solo por fuera.
REM          build_exe.bat ya usa --clean, así que recompilar no
REM          hace daño aunque no haya cambiado nada.)
REM  Paso 2: compila el instalador con Inno Setup
REM ============================================================
cd /d "%~dp0"

REM --- Paso 1: build de PyInstaller ---
call build_exe.bat
if not exist "dist\QuoteTrip\QuoteTrip.exe" (
  echo ERROR: no se pudo compilar la app. Revisa build_exe.bat.
  pause & exit /b 1
)

REM --- Paso 2: localizar Inno Setup (ISCC.exe) ---
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo.
  echo No se encontro Inno Setup 6.
  echo Descargalo gratis en:  https://jrsoftware.org/isdl.php
  echo Instalalo y vuelve a ejecutar este archivo.
  pause & exit /b 1
)

echo Compilando el instalador...
"%ISCC%" installer.iss

echo.
if exist "Output\QuoteTrip-Setup.exe" (
  echo ============================================================
  echo  LISTO. Instalador generado en:
  echo    Output\QuoteTrip-Setup.exe
  echo  Ese unico archivo se instala en cualquier Windows nuevo.
  echo ============================================================
) else (
  echo ERROR: no se genero el instalador. Revisa los mensajes de arriba.
)
pause