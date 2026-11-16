# Push this folder into Fusion's AddIns directory.
# ColorMap.py is the shell - changing it needs the add-in stopped and re-run.
# cm_core.py hot-reloads: pushing it takes effect on the next command.
$src = Split-Path -Parent $MyInvocation.MyCommand.Definition
$dst = Join-Path $env:APPDATA 'Autodesk\Autodesk Fusion 360\API\AddIns\ColorMap'

New-Item -ItemType Directory -Force -Path $dst | Out-Null

$cache = Join-Path $dst '__pycache__'
if (Test-Path -LiteralPath $cache) { Remove-Item -LiteralPath $cache -Recurse -Force }

# every runtime file - keep this list in step with the imports
foreach ($f in @('ColorMap.py', 'cm_core.py', 'ColorMap.manifest')) {
    Copy-Item -LiteralPath (Join-Path $src $f) -Destination $dst -Force
}
# replace, not merge: Copy-Item -Recurse into an existing folder nests it
$resDst = Join-Path $dst 'resources'
if (Test-Path -LiteralPath $resDst) { Remove-Item -LiteralPath $resDst -Recurse -Force }
Copy-Item -LiteralPath (Join-Path $src 'resources') -Destination $dst -Recurse -Force

Write-Host "Installed to $dst"
