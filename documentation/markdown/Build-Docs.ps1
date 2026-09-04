<#
.SYNOPSIS
    Converts the Markdown documentation to Word and/or PDF documents,
    rendering any Mermaid diagrams to images along the way.

.DESCRIPTION
    Reads every .md file under markdown\en and markdown\ja and writes the
    corresponding document to docx\<lang> and pdf\<lang>.

    Pandoc cannot render Mermaid on its own: a fenced mermaid block would be
    carried through as literal code. Each block is therefore rendered to PNG
    with mermaid-cli first, and the block is replaced by an image reference in
    a temporary copy of the Markdown. The source files are never modified.

    PDFs are produced by converting the generated .docx with LibreOffice
    rather than by a separate pandoc PDF engine. That keeps both formats
    identical: one layout, one set of fonts, one document to review.

    A document that is newer than its .md is left alone, so hand-editing a
    generated file is not silently undone. Pass -Force to rebuild anyway.

.PARAMETER Format
    Which output to produce: docx, pdf, or all. Defaults to all.

.PARAMETER Language
    Which folder to build: en, ja, or all. Defaults to all.

.PARAMETER Name
    Build only files whose name matches this wildcard, e.g. Project*.

.PARAMETER Force
    Rebuild even when the existing document is newer than the .md.

.PARAMETER Scale
    Mermaid render scale. Higher is sharper and larger. Defaults to 2.

.PARAMETER Width
    Mermaid render width in pixels before scaling. Defaults to 1400.

.PARAMETER Toc
    Insert a table of contents.

.PARAMETER KeepIntermediate
    Leave the working directory in place so the generated PNGs can be
    inspected when a diagram does not look right.

.EXAMPLE
    .\Build-Docs.ps1

.EXAMPLE
    .\Build-Docs.ps1 -Format pdf

.EXAMPLE
    .\Build-Docs.ps1 -Language ja -Force

.EXAMPLE
    .\Build-Docs.ps1 -Name "Project*" -KeepIntermediate
#>
[CmdletBinding()]
param(
    [ValidateSet('docx', 'pdf', 'all')]
    [string]$Format = 'all',

    [ValidateSet('en', 'ja', 'all')]
    [string]$Language = 'all',

    [string]$Name = '*',

    [switch]$Force,

    [int]$Scale = 2,

    [int]$Width = 1400,

    [switch]$Toc,

    [switch]$KeepIntermediate
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

$markdownRoot = $PSScriptRoot
$docsRoot     = Split-Path -Parent $markdownRoot
$docxRoot     = Join-Path $docsRoot 'docx'
$pdfRoot      = Join-Path $docsRoot 'pdf'
$templateDir  = Join-Path $markdownRoot '_templates'

if ($Language -eq 'all') {
    $languages = @('en', 'ja')
}
else {
    $languages = @($Language)
}

if ($Format -eq 'all') {
    $formats = @('docx', 'pdf')
}
else {
    $formats = @($Format)
}

$wantDocx = $formats -contains 'docx'
$wantPdf  = $formats -contains 'pdf'

# --------------------------------------------------------------------------
# Tool checks
# --------------------------------------------------------------------------

if (-not (Get-Command 'pandoc' -ErrorAction SilentlyContinue)) {
    throw 'pandoc was not found on PATH. Install it with: winget install --id JohnMacFarlane.Pandoc'
}

if (-not (Get-Command 'mmdc' -ErrorAction SilentlyContinue)) {
    throw 'mmdc was not found on PATH. Install it with: npm install -g @mermaid-js/mermaid-cli'
}

# LibreOffice is normally installed without being added to PATH, so fall back
# to the usual install locations before giving up.
$soffice = $null
if ($wantPdf) {
    $sofficeCommand = Get-Command 'soffice' -ErrorAction SilentlyContinue
    if ($sofficeCommand) {
        $soffice = $sofficeCommand.Source
    }
    else {
        $candidates = @(
            (Join-Path $env:ProgramFiles 'LibreOffice\program\soffice.exe')
            (Join-Path ${env:ProgramFiles(x86)} 'LibreOffice\program\soffice.exe')
        )
        $soffice = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }

    if (-not $soffice) {
        throw 'LibreOffice was not found. It is required for PDF output. Install it with: winget install --id TheDocumentFoundation.LibreOffice'
    }
}

# --------------------------------------------------------------------------
# Mermaid configuration
#
# Headless Chromium picks its own default font, which has no CJK coverage.
# Without this the Japanese diagrams render as empty boxes.
# --------------------------------------------------------------------------

$mermaidConfigJson = @'
{
  "theme": "default",
  "themeVariables": {
    "fontFamily": "Yu Gothic, Meiryo, Segoe UI, sans-serif",
    "fontSize": "16px"
  },
  "sequence": {
    "actorFontFamily": "Yu Gothic, Meiryo, sans-serif",
    "noteFontFamily": "Yu Gothic, Meiryo, sans-serif",
    "messageFontFamily": "Yu Gothic, Meiryo, sans-serif"
  }
}
'@

$puppeteerConfigJson = '{ "args": ["--no-sandbox"] }'

# Fenced mermaid block, from its opening fence to its closing fence.
$mermaidPattern = '(?ms)^```mermaid[ \t]*\r?\n(.*?)\r?\n[ \t]*```[ \t]*$'

# --------------------------------------------------------------------------
# Word to PDF
#
# LibreOffice refuses to run headless while a normal instance is open unless
# it is given a profile of its own, so always hand it a throwaway one.
# --------------------------------------------------------------------------

function Convert-DocxToPdf {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$DocxPath,
        [Parameter(Mandatory = $true)][string]$OutputDir,
        [Parameter(Mandatory = $true)][string]$ProfileDir
    )

    $profileUri = 'file:///' + ($ProfileDir -replace '\\', '/')

    & $Executable "-env:UserInstallation=$profileUri" `
                  '--headless' '--norestore' `
                  '--convert-to' 'pdf' `
                  '--outdir' $OutputDir `
                  $DocxPath | Out-Null

    $produced = Join-Path $OutputDir ([System.IO.Path]::GetFileNameWithoutExtension($DocxPath) + '.pdf')

    # LibreOffice reports success even when it has silently skipped a file,
    # so confirm the output actually exists rather than trusting the exit code.
    if (-not (Test-Path -LiteralPath $produced)) {
        throw ('LibreOffice did not produce ' + (Split-Path -Leaf $produced))
    }

    return $produced
}

# --------------------------------------------------------------------------
# Build one file
# --------------------------------------------------------------------------

function Convert-Markdown {
    param(
        [Parameter(Mandatory = $true)][System.IO.FileInfo]$Source,
        [string]$DocxPath,
        [string]$PdfPath,
        [string]$ReferenceDoc
    )

    $workDir = Join-Path $env:TEMP ('docbuild-' + [guid]::NewGuid().ToString('n'))
    $imageDir = Join-Path $workDir 'images'
    New-Item -ItemType Directory -Path $imageDir -Force | Out-Null

    try {
        $mermaidConfig = Join-Path $workDir 'mermaid-config.json'
        $puppeteerConfig = Join-Path $workDir 'puppeteer-config.json'
        [System.IO.File]::WriteAllText($mermaidConfig, $mermaidConfigJson, $utf8NoBom)
        [System.IO.File]::WriteAllText($puppeteerConfig, $puppeteerConfigJson, $utf8NoBom)

        $content = [System.IO.File]::ReadAllText($Source.FullName, [System.Text.Encoding]::UTF8)
        $blocks = [regex]::Matches($content, $mermaidPattern)

        $builder = New-Object System.Text.StringBuilder
        $cursor = 0
        $index = 0

        foreach ($block in $blocks) {
            $index++

            [void]$builder.Append($content.Substring($cursor, $block.Index - $cursor))

            $diagramName = 'diagram-{0:d2}' -f $index
            $mmdFile = Join-Path $workDir ($diagramName + '.mmd')
            $pngFile = Join-Path $imageDir ($diagramName + '.png')

            [System.IO.File]::WriteAllText($mmdFile, $block.Groups[1].Value, $utf8NoBom)

            Write-Host ("      diagram {0}/{1}" -f $index, $blocks.Count) -ForegroundColor DarkGray

            & mmdc -i $mmdFile -o $pngFile -c $mermaidConfig -p $puppeteerConfig `
                   -b white -s $Scale -w $Width | Out-Null

            if ($LASTEXITCODE -ne 0) {
                throw ('mmdc failed on diagram ' + $index + ' of ' + $Source.Name +
                       '. Re-run with -KeepIntermediate and try: mmdc -i "' + $mmdFile + '" -o out.png')
            }

            [void]$builder.Append('![](images/' + $diagramName + '.png)')

            $cursor = $block.Index + $block.Length
        }

        [void]$builder.Append($content.Substring($cursor))

        $buildMd = Join-Path $workDir ($Source.BaseName + '.build.md')
        [System.IO.File]::WriteAllText($buildMd, $builder.ToString(), $utf8NoBom)

        # The PDF is made from the .docx, so a .docx is always produced. When
        # only a PDF was asked for it goes to the working directory and is
        # discarded with it.
        if ($DocxPath) {
            $docxTarget = $DocxPath
        }
        else {
            $docxTarget = Join-Path $workDir ($Source.BaseName + '.docx')
        }

        # Matching the DPI to the render scale keeps the images at their
        # intended physical size rather than spanning several pages.
        $pandocArgs = @(
            $buildMd
            '-o'; $docxTarget
            '--dpi'; "$(96 * $Scale)"
            '--from'; 'gfm'
            # Image paths are relative to the build file, but pandoc resolves
            # them against the working directory unless told otherwise.
            '--resource-path'; $workDir
        )

        if ($Toc) {
            $pandocArgs += @('--toc', '--toc-depth=2')
        }

        if ($ReferenceDoc) {
            $pandocArgs += @('--reference-doc', $ReferenceDoc)
        }

        & pandoc @pandocArgs

        if ($LASTEXITCODE -ne 0) {
            throw ('pandoc failed on ' + $Source.Name)
        }

        if ($PdfPath) {
            $profileDir = Join-Path $workDir 'lo-profile'
            $outputDir = Split-Path -Parent $PdfPath

            $produced = Convert-DocxToPdf -Executable $soffice `
                                          -DocxPath $docxTarget `
                                          -OutputDir $outputDir `
                                          -ProfileDir $profileDir

            # LibreOffice names the output after the .docx. Rename only when
            # the caller asked for something else.
            if ($produced -ne $PdfPath) {
                Move-Item -LiteralPath $produced -Destination $PdfPath -Force
            }
        }

        return $blocks.Count
    }
    finally {
        if ($KeepIntermediate) {
            Write-Host ("      intermediate files: {0}" -f $workDir) -ForegroundColor DarkGray
        }
        elseif (Test-Path -LiteralPath $workDir) {
            Remove-Item -LiteralPath $workDir -Recurse -Force
        }
    }
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

$built = 0
$skipped = 0
$failed = 0

foreach ($lang in $languages) {

    $sourceDir = Join-Path $markdownRoot $lang
    $docxDir   = Join-Path $docxRoot $lang
    $pdfDir    = Join-Path $pdfRoot $lang

    if (-not (Test-Path -LiteralPath $sourceDir)) {
        Write-Warning ("No such folder: {0}" -f $sourceDir)
        continue
    }

    foreach ($dir in @($docxDir, $pdfDir)) {
        if (-not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    # A reference document supplies the fonts and styles. Language-specific
    # by convention, falling back to a shared one.
    $referenceDoc = $null
    foreach ($candidate in @(('reference-' + $lang + '.docx'), 'reference.docx')) {
        $path = Join-Path $templateDir $candidate
        if (Test-Path -LiteralPath $path) {
            $referenceDoc = (Resolve-Path -LiteralPath $path).Path
            break
        }
    }

    Write-Host ''
    Write-Host ("[{0}] {1}" -f $lang, $sourceDir) -ForegroundColor Cyan
    Write-Host ("      output: {0}" -f ($formats -join ', ')) -ForegroundColor DarkGray
    if ($referenceDoc) {
        Write-Host ("      style: {0}" -f (Split-Path -Leaf $referenceDoc)) -ForegroundColor DarkGray
    }

    $sources = Get-ChildItem -LiteralPath $sourceDir -Filter '*.md' -File |
               Where-Object { $_.Name -like $Name } |
               Sort-Object Name

    if ($sources.Count -eq 0) {
        Write-Host '      (no matching markdown files)' -ForegroundColor DarkGray
        continue
    }

    foreach ($source in $sources) {

        $docxPath = if ($wantDocx) { Join-Path $docxDir ($source.BaseName + '.docx') } else { $null }
        $pdfPath  = if ($wantPdf)  { Join-Path $pdfDir  ($source.BaseName + '.pdf')  } else { $null }

        # Only skip when every requested output is already up to date.
        if (-not $Force) {
            $targets = @($docxPath, $pdfPath) | Where-Object { $_ }
            $upToDate = $targets | Where-Object {
                (Test-Path -LiteralPath $_) -and
                ((Get-Item -LiteralPath $_).LastWriteTime -gt $source.LastWriteTime)
            }

            if ($upToDate.Count -eq $targets.Count) {
                Write-Host ("  skip  {0}" -f $source.Name) -ForegroundColor Yellow
                Write-Host '        the generated files are newer than the .md; use -Force to overwrite' -ForegroundColor DarkGray
                $skipped++
                continue
            }
        }

        Write-Host ("  build {0}" -f $source.Name) -ForegroundColor Green

        try {
            $diagramCount = Convert-Markdown -Source $source `
                                             -DocxPath $docxPath `
                                             -PdfPath $pdfPath `
                                             -ReferenceDoc $referenceDoc

            foreach ($target in @($docxPath, $pdfPath) | Where-Object { $_ }) {
                Write-Host ("        -> {0}" -f (Split-Path -Leaf $target)) -ForegroundColor DarkGray
            }
            Write-Host ("        {0} diagram(s)" -f $diagramCount) -ForegroundColor DarkGray

            $built++
        }
        catch {
            Write-Host ("        FAILED: {0}" -f $_.Exception.Message) -ForegroundColor Red
            $failed++
        }
    }
}

Write-Host ''
Write-Host ("Built {0}, skipped {1}, failed {2}." -f $built, $skipped, $failed)

if ($failed -gt 0) {
    exit 1
}
