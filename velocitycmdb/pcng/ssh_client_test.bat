@echo off
setlocal

set HOST_IP=172.16.10.2
set KEY_PATH=C:\Users\speterman\.ssh\id_rsa

echo ================================================================================
echo Testing Cisco Account (Password Auth)
echo ================================================================================
python ssh_client_test.py --host %HOST_IP% --user cisco --password cisco --tests 1,5

echo.
echo.
echo ================================================================================
echo Testing Speterman Account (Key Auth - All Methods)
echo ================================================================================
REM Run all key-based tests with password fallback
python ssh_client_test.py --host %HOST_IP% --user speterman --key %KEY_PATH% --password cisco

echo.
echo.
echo ================================================================================
echo Testing Environment Variables
echo ================================================================================
set PYSSH_PASS=cisco
python ssh_client_test.py --host %HOST_IP% --user cisco --tests 5

set PYSSH_KEY=%KEY_PATH%
python ssh_client_test.py --host %HOST_IP% --user speterman --tests 6

echo.
echo.
echo ================================================================================
echo Testing Multiple Key Types (Cisco Account)
echo ================================================================================
python ssh_client_test.py --host %HOST_IP% --user cisco --password cisco --tests 8

endlocal