param([string]$OutputPath = (Join-Path (Split-Path -Parent $PSScriptRoot) '..\submission_package_v2.zip'))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$rootUri = [Uri]($root.TrimEnd('\') + '\')
$output = [IO.Path]::GetFullPath($OutputPath)
New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($output)) | Out-Null
$mode = [System.IO.Compression.ZipArchiveMode]::Create
if (Test-Path -LiteralPath $output) {
    $probe = [System.IO.Compression.ZipFile]::OpenRead($output)
    try {
        if ($probe.Entries.Count -ne 0) { throw "Output already contains entries; choose a new path: $output" }
    } finally { $probe.Dispose() }
    $mode = [System.IO.Compression.ZipArchiveMode]::Update
}
$archive = [System.IO.Compression.ZipFile]::Open($output,$mode)
try {
    foreach ($file in [System.IO.Directory]::EnumerateFiles($root,'*',[System.IO.SearchOption]::AllDirectories)) {
        $relative = [Uri]::UnescapeDataString($rootUri.MakeRelativeUri([Uri]$file).ToString()).Replace('/','\')
        $parts = $relative -split '[\\/]'
        if ($relative -match '^(experiments[\\/]local_runs|st[\\/]pilot)([\\/]|$)') { continue }
        if ($parts | Where-Object { $_ -match '^\.env($|\.)|^config\.local\.json$|^~\$' }) { continue }
        if ($parts -contains '.git' -or $parts -contains 'node_modules' -or
            $parts -contains '__pycache__' -or $file.EndsWith('.pyc')) { continue }
        if (($parts -contains 'report') -and ([IO.Path]::GetExtension($file) -eq '.pdf') -and
            ([IO.Path]::GetFileNameWithoutExtension($file) -match '_QA$')) { continue }
        $entryName = 'submission/' + ($relative -replace '\\','/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,$file,$entryName,[System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally {
    $archive.Dispose()
}
$check = [System.IO.Compression.ZipFile]::OpenRead($output)
try {
    $entries = @($check.Entries)
    foreach ($report in @('submission/report/project_report_en.docx','submission/report/project_report_en.pdf')) {
        if (!($entries.FullName -contains $report)) { throw "English report missing from package: $report" }
    }
    if (!($entries.FullName -contains 'submission/dataset/tasks.json')) { throw 'Dataset missing from package' }
    if (!($entries.FullName -contains 'submission/experiments/results.csv')) { throw 'Experiment matrix missing from package' }
    if ($entries | Where-Object { $_.FullName -match '(^|/)(\.git|node_modules|__pycache__)/|(^|/)(experiments/local_runs|st/pilot)(/|$)|\.pyc$|_QA\.pdf$' }) { throw 'Unexpected generated or QA files in package' }
    Write-Output "Entries: $($entries.Count)"
    Write-Output "Report, dataset and matrix present."
} finally {
    $check.Dispose()
}
Get-Item -LiteralPath $output | Select-Object FullName,Length
