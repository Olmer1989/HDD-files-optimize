@echo off
rem Starts the single .ps1 that lies next to this file. No execution policy question, the policy itself is not changed.
rem Copy template 2.4 and newer (2.5, 2.6): own arguments go to the script (the window queue passes -Confirmed -Expect ...), its exit code is returned.
for %%F in ("%~dp0*.ps1") do powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%%F" %*
exit /b %errorlevel%
