Option Explicit
Dim shell, fso, base, desktop, link, quiet
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
desktop = shell.SpecialFolders("Desktop")
quiet = False
If WScript.Arguments.Count > 0 Then
  quiet = (LCase(WScript.Arguments(0)) = "/quiet")
End If

Set link = shell.CreateShortcut(desktop & "\Parroty.lnk")
link.TargetPath = shell.ExpandEnvironmentStrings("%SystemRoot%\System32\wscript.exe")
link.Arguments = "//nologo " & Chr(34) & base & "\launch_parroty.vbs" & Chr(34)
link.WorkingDirectory = base
link.Description = "Parroty audiobook creator"
link.IconLocation = shell.ExpandEnvironmentStrings("%SystemRoot%\System32\imageres.dll,15")
link.Save

If Not quiet Then MsgBox "Parroty shortcut created on your desktop.", 64, "Parroty"
