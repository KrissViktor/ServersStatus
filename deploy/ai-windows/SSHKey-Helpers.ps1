#Requires -Version 5.1
function Protect-AITunnelKey {
    param([string]$Path)
    if(!(Test-Path -LiteralPath $Path -PathType Leaf)){throw 'SSH private key not found'}
    if((Get-Item -LiteralPath $Path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Refusing a reparse-point SSH key'}
    $admins=New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $system=New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
    # Fresh protected DACL removes inherited AND explicit creator/LocalService/user ACEs.
    # OpenSSH running as SYSTEM accepts owner SYSTEM or Builtin Administrators,
    # not the individual administrator who originally generated the file.
    $acl=New-Object Security.AccessControl.FileSecurity
    $acl.SetOwner($admins)
    $acl.SetAccessRuleProtection($true,$false)
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($admins,'FullControl','Allow')))
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($system,'FullControl','Allow')))
    Set-Acl -LiteralPath $Path -AclObject $acl
}
