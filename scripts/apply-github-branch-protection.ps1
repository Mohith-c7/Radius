param(
    [string]$Owner = "Mohith-c7",
    [string]$Repo = "Radius",
    [string]$DefaultBranch = "dev",
    [string]$ApiVersion = "2022-11-28",
    [string]$Token = $env:GITHUB_TOKEN
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Token)) {
    throw "Set GITHUB_TOKEN to a GitHub token with Administration: write permission for $Owner/$Repo."
}

$headers = @{
    Accept                 = "application/vnd.github+json"
    Authorization          = "Bearer $Token"
    "X-GitHub-Api-Version" = $ApiVersion
}

function Invoke-GitHubJson {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [object]$Body
    )

    $params = @{
        Method  = $Method
        Uri     = $Uri
        Headers = $headers
    }

    if ($null -ne $Body) {
        $params.Body = ($Body | ConvertTo-Json -Depth 20)
        $params.ContentType = "application/json"
    }

    Invoke-RestMethod @params
}

function Protect-Branch {
    param(
        [Parameter(Mandatory = $true)][string]$Branch,
        [Parameter(Mandatory = $true)][int]$RequiredApprovals,
        [Parameter(Mandatory = $true)][bool]$RequireCodeOwnerReview
    )

    $encodedBranch = [uri]::EscapeDataString($Branch)
    $baseUri = "https://api.github.com/repos/$Owner/$Repo/branches/$encodedBranch/protection"

    $payload = @{
        required_status_checks           = @{
            strict   = $true
            contexts = @("Validate")
        }
        enforce_admins                   = $true
        required_pull_request_reviews    = @{
            dismissal_restrictions          = @{
                users = @()
                teams = @()
                apps  = @()
            }
            dismiss_stale_reviews           = $true
            require_code_owner_reviews      = $RequireCodeOwnerReview
            required_approving_review_count = $RequiredApprovals
            require_last_push_approval      = $true
            bypass_pull_request_allowances  = @{
                users = @()
                teams = @()
                apps  = @()
            }
        }
        restrictions                       = $null
        required_linear_history            = $true
        allow_force_pushes                 = $false
        allow_deletions                    = $false
        block_creations                    = $false
        required_conversation_resolution   = $true
        lock_branch                        = $false
        allow_fork_syncing                 = $true
    }

    Write-Host "Applying branch protection to $Branch..."
    Invoke-GitHubJson -Method Put -Uri $baseUri -Body $payload | Out-Null

    Write-Host "Requiring signed commits on $Branch..."
    Invoke-GitHubJson -Method Post -Uri "$baseUri/required_signatures" | Out-Null
}

Write-Host "Setting default branch to $DefaultBranch..."
Invoke-GitHubJson `
    -Method Patch `
    -Uri "https://api.github.com/repos/$Owner/$Repo" `
    -Body @{ default_branch = $DefaultBranch } | Out-Null

Protect-Branch -Branch "dev" -RequiredApprovals 1 -RequireCodeOwnerReview $false
Protect-Branch -Branch "main" -RequiredApprovals 2 -RequireCodeOwnerReview $true

Write-Host "Default branch set to $DefaultBranch."
Write-Host "Branch protection applied for $Owner/$Repo on dev and main."
