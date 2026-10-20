' Starts Little with no black console window behind it.
' Prefers the web interface, falls back to the plain window.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here

python = here & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(python) Then python = "pythonw.exe"

app = here & "\launcher_web.py"
If Not fso.FileExists(app) Then app = here & "\launcher.py"

shell.Run """" & python & """ """ & app & """", 0, False
