<#
 build-docker-bake.ps1
 ---------------------------------------------------------------
 • Menú de selección de servicios desde docker-compose
 • Opción 999  → exportar .tar sin compilar
 • Buildx Bake (con --load) para compilar
 • Git pull opcional, --no-cache, prune de caché buildx
 • Export post-build opcional, listado final
#>

#region ─── Entrada de usuario ──────────────────────────────────────────────
$composeFile = Read-Host "Enter docker-compose filename (default: docker-compose)"
if (-not $composeFile) { $composeFile = "docker-compose" }
$composeFile = "$composeFile.yml"

if (-not (Test-Path $composeFile)) {
    Write-Host "[ERROR] File '$composeFile' does not exist." -ForegroundColor Red
    exit 1
}

try   { docker info | Out-Null }
catch { Write-Host "[ERROR] Docker is not running." -ForegroundColor Red; exit 1 }
#endregion

#region ─── Analizar docker-compose y preparar menú ─────────────────────────
Write-Host "`nReading $composeFile ..."
$json     = docker compose -f $composeFile config --format json | ConvertFrom-Json
$services = $json.services

$svcList = @(); $i = 0
foreach ($name in $services.PSObject.Properties.Name) {
    $svc = $services.$name
    if ($svc.image) {
        $i++
        $svcList += [PSCustomObject]@{
            Index   = $i
            Service = $name
            Image   = $svc.image
            Raw     = $svc
        }
    }
}

# ── Mostrar opciones ──────────────────────────────────────────────────────
Write-Host "`nSelect a service or choose an option:"
$svcList | ForEach-Object { Write-Host "$($_.Index). $($_.Service) - $($_.Image)" }
$choice = Read-Host "0 = All | 999 = export-only | or numbers (e.g. 2 or 1 3)"

$selected = @()   # ← array final con los servicios elegidos

switch ($true) {
    { $choice -eq "0" } {
        $selected = $svcList
        Write-Host "Selected: All services"
        Write-Host $selected 
        break
    }
    { $choice -match '^\d+$' } {              # una sola opción
        $selected = ,$svcList[[int]$choice - 1]
         break
    }

    { $choice -match '^\d+(?:\s+\d+)+$' } {   # varias
        $selected = $choice -split '\s+' | ForEach-Object { $svcList[[int]$_ - 1] }
         break
    }
    { $choice -eq "999" } {
        Write-Host "[SAVE ONLY] Selected: Export images only - no build will be done."

        $path = Read-Host "Enter the path to export images as .tar (e.g. C:\images)"
        if (-not (Test-Path $path)) {
            Write-Host "[X] Path does not exist: $path" -f Red
            exit 1
        }

        $indexes = Read-Host "Enter the service numbers to export (e.g. 2 5 or 0 for All)"
        if ($indexes -eq "0") {
            $selected = $svcList
        } else {
            $selected = $indexes -split '\s+' | ForEach-Object { $svcList[[int]$_ - 1] }
        }

        $totalServices = $selected.Count
        $currentService = 0

        foreach ($service in $selected) {
            $image = $service.Image
            $version = $image.Split(":")[1]
            $imageName = $image.Split(":")[0] -replace "/", "_"

            if ($imageName -match "[^\w\.\-]") {
                Write-Host "[ERROR] Invalid image name: $image"
                exit 1
            }

            $fileName = "$($imageName)_v$version.tar"
            if ($path[-1] -ne '\') { $path += "\" }
            $filePath = "$path$fileName"

            Write-Host "Exporting image $imageName..."
            Write-Progress -PercentComplete ([math]::Round(($currentService / $totalServices) * 100)) `
                        -Status "Exporting $imageName" -Activity "Saving .tar file"

            try {
                docker save -o "$filePath" "$image"
                if ($?) {
                    Write-Host "Exported: $filePath"
                } else {
                    Write-Host "[ERROR] Failed to export image: $image"
                    exit 1
                }
            } catch {
                Write-Host "[ERROR] Exception while exporting image: $image"
                exit 1
            }

            $currentService++
        }
        Write-Host "Images exported successfully."
        exit 0
    }
    default {
        Write-Host "[X] Invalid selection: $choice" -f Red
        exit 1
    }

}
#endregion


#region ─── Git pull opcional (bloque completo) ─────────────────────────────
foreach ($service in $selected) {
    Write-Host "Checking Git for $($service.Service)..."
    if ($service.Raw.PSObject.Properties["build"] -and $service.Raw.build.PSObject.Properties["context"]) {
        $contextPath = $service.Raw.build.context
        if ((Test-Path $contextPath) -and (Test-Path "$contextPath\.git")) {

            $updateGit = Read-Host "Do you want to update the Git repo in $contextPath? (y/N)"
            if ($updateGit -eq "y") {
                Write-Host "Preparing to update Git repository in $contextPath..."
                Push-Location $contextPath

                # Get current branch
                $currentBranch = git rev-parse --abbrev-ref HEAD
                Write-Host "Current branch: $currentBranch"

                # If not on develop, offer to switch
                if ($currentBranch -ne "develop") {
                    $switch = Read-Host "You're on '$currentBranch'. Switch to 'develop'? (y/N)"
                    if ($switch -eq "y") {

                        # Check for uncommitted changes
                        $hasChanges = git status --porcelain
                        if ($hasChanges) {
                            Write-Host "Uncommitted changes detected:"
                            git status -s

                            $commitChoice = Read-Host "Commit changes before switch? (y/N)"
                            if ($commitChoice -eq "y") {
                                git add .

                                $commitMessage = Read-Host "Enter a commit message"
                                git commit -m "$commitMessage"
                                Write-Host "Changes committed."
                            } else {
                                Write-Host "Skipping commit."
                            }
                        }

                        git checkout develop
                    }
                }

                # Pull latest changes from develop
                git pull origin develop

                Pop-Location
            }
        }
    }
}
#endregion

#region ─── Preguntar versión y construir --set ─────────────────────────────
$setArgs     = @()
$tagToLatest = @()

foreach ($svc in $selected) {
    Write-Host "`nService: $($svc.Service)" -ForegroundColor Yellow
    $img          = $svc.Image
    $parts        = $img -split ':', 2
    $repo         = $parts[0]
    $ver          = if ($parts.Count -gt 1 -and $parts[1]) { $parts[1] } else { "latest" }

    Write-Host "`nImage detected:" -NoNewline
    Write-Host " $($repo):$ver" -ForegroundColor Cyan

    $answer = Read-Host "Is this the correct version tag? (Y/n)"
    if ($answer -and $answer.ToLower() -eq "n") {
        $ver = Read-Host "Enter version for $($svc.Service)"
    }

    # --set <target>.tags=<repo>:<ver>
    $setArgs     += "--set", "$($svc.Service).tags=$repo`:$ver"
    $tagToLatest += [PSCustomObject]@{ Repo = $repo; Ver = $ver }
}
#endregion

#region ─── Buildx Bake robusto ─────────────────────────────────────────────
$useCache = Read-Host "Use cache for image build? (Y/n)"
$noCacheFlag = if ($useCache -eq "n") { "--no-cache" } else { $null }

$targetList = $selected | ForEach-Object { $_.Service }

# Arma el arreglo *en orden*   [flags...] [targets...]
$bakeArgs = @(
    "-f", $composeFile,
    "--load",
    $noCacheFlag,
    $setArgs,          # ← ya es array "--set", "svc.tags=repo:ver", ...
    "--progress=auto"
) + $targetList        # ← finalmente los targets

# Limpia nulos/vacíos (por si $noCacheFlag no aplica)
$bakeArgs = $bakeArgs | Where-Object { $_ }

Write-Host "`nRunning: docker buildx bake $($bakeArgs -join ' ')"

# Usa el operador call (&) para splat completo sin comillas
& docker buildx bake @bakeArgs
if ($LASTEXITCODE) { Write-Host "[ERROR] Bake failed." -ForegroundColor Red ; exit 1 }
Write-Host "`n[OK] Bake finished." -ForegroundColor Green
#endregion

#region ─── Etiquetar :latest ───────────────────────────────────────────────
foreach ($t in $tagToLatest) {
    docker tag "$($t.Repo):$($t.Ver)" "$($t.Repo):latest"
}
#endregion

#region ─── Exportar imágenes compiladas (opcional) ─────────────────────────
$export = Read-Host "`nExport the images as .tar files? (y/N)"
if ($export -and $export.ToLower() -eq "y") {

    $path = Read-Host "Enter target directory path (e.g. C:\images)"
    if (-not (Test-Path $path)) {
        Write-Host "[ERROR] Path does not exist: $path" -ForegroundColor Red
        exit 1
    }

    $totalServices  = $selected.Count
    $currentService = 0

    foreach ($svc in $selected) {
        $image      = $svc.Image
        $version    = $image.Split(":")[1]
        $imageName  = $image.Split(":")[0] -replace "/", "_"
        $fileName   = "${imageName}_${composeFile}_v${version}.tar"
        $filePath   = Join-Path $path $fileName

        Write-Host "Exporting" -NoNewline
        Write-Host " $imageName" -ForegroundColor Cyan -NoNewline
        Write-Host " -} $fileName"

        Write-Progress -PercentComplete (
            [math]::Round(($currentService / $totalServices) * 100)
        ) -Status "Saving $fileName" -Activity "Exporting images"

        docker save -o $filePath $image
        if ($?) {
            Write-Host "[OK] Saved $fileName" -ForegroundColor Green
        } else {
            Write-Host "[ERROR] Failed to export $image" -ForegroundColor Red
            exit 1
        }

        $currentService++
    } # ← cierra foreach

    Write-Host "`nImages exported successfully." -ForegroundColor Green
} # ← cierra if ($export)

#endregion


#region ─── Prune imágenes dangling ─────────────────────────────────────────
Write-Host "`nPruning dangling images..." -ForegroundColor DarkGray
# Clean up dangling images
$danglingImages = docker images -f "dangling=true" -q
foreach ($imageId in $danglingImages) {
    Write-Host " Processing image: $imageId"
    $containerIds = docker ps -a -q --filter ancestor=$imageId
    if ($containerIds) {
        Write-Host "[X] Stopping containers using this image..."
        $containerIds | ForEach-Object { docker stop $_ }
        Write-Host "[...] Removing containers..."
        $containerIds | ForEach-Object { docker rm $_ }
    } else {
        Write-Host "[OK] No containers using this image."
    }
    Write-Host " Removing image $imageId..."
    docker rmi $imageId
}
#endregion

#region ─── Limpieza de caché buildx ────────────────────────────────────────
if ((Read-Host "`nClean buildx cache? (y/N)") -eq "y") {
    Write-Host "`nRunning: docker buildx prune --all --force"
    docker buildx prune --all --force
}
#endregion

#region ─── Listado final ───────────────────────────────────────────────────
Write-Host "`n--- Built images ---" -ForegroundColor Cyan
foreach ($svc in $selected) {
    docker images --format "{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}" |
        Where-Object { $_ -like "$($svc.Image)*" } |
        ForEach-Object { Write-Host $_ }
}
Write-Host "`nProcess completed." -ForegroundColor Cyan
#endregion
