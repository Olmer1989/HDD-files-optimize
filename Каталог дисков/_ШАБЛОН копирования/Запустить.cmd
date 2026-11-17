@echo off
rem Starts the single .ps1 that lies next to this file. No execution policy question, the policy itself is not changed.
rem Copy template 2.4 and newer (2.5, 2.6, 2.7): own arguments go to the script (the window queue passes -Confirmed -Expect ...), its exit code is returned.
rem Template 2.8 is in parts: the parts are *.psm1 next to the script, the mask *.ps1 does not start them.
for %%F in ("%~dp0*.ps1") do powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%%F" %*
exit /b %errorlevel%
