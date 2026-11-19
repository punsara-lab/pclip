@echo off
rem Wrapper to run pclip-tunnel.ps1 without changing system execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pclip-tunnel.ps1"
