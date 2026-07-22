Option Explicit
Dim shell, fso, base, pyw, cmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)

If fso.FileExists(base & "\venv\Scripts\pythonw.exe") Then
  pyw = base & "\venv\Scripts\pythonw.exe"
ElseIf fso.FileExists(base & "\.venv\Scripts\pythonw.exe") Then
  pyw = base & "\.venv\Scripts\pythonw.exe"
Else
  pyw = "pythonw.exe"
End If

shell.CurrentDirectory = base
shell.Environment("PROCESS")("PARROTY_HIDDEN") = "1"
cmd = Chr(34) & pyw & Chr(34) & " " & Chr(34) & base & "\launch_parroty.pyw" & Chr(34)
shell.Run cmd, 0, False
