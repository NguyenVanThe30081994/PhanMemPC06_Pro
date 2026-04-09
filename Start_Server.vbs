Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' Lay thu muc chua file .vbs nay
strDir = FSO.GetParentFolderName(WScript.ScriptFullName)

' Chay Start_Server.bat voi cua so CMD hien thi (Normal Window)
' Tham so: 1 = Activate and display window, False = don't wait
WshShell.Run "cmd.exe /k ""cd /d """ & strDir & """ && Start_Server.bat""", 1, False

