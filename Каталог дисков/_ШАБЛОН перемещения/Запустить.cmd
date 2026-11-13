@echo off
rem Starts the single .ps1 that lies next to this file. No execution policy question, the policy itself is not changed.
for %%F in ("%~dp0*.ps1") do powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%%F"
