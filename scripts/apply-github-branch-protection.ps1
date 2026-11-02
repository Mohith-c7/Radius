param(
    [string]$Owner = "Mohith-c7",
    [string]$Repo = "Radius",
    [string]$DefaultBranch = "develop",
    [string]$ApiVersion = "2022-11-28",
    [string]$Token = $env:GITHUB_TOKEN
)

# Applies the configuration documented in docs/github-branch-protection.md.
# Flow: feature/* -> develop -> dev (UAT) -> main.
# Deliberately NOT set: signed commits, linear history, strict status checks,
# enforce_admins (solo owner bypasses as admin; see the doc for when to tighten).
# "Dependency audit (pnpm)" is not required because its baseline expires 2027-01-31.

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Token)) {
    throw "Set GITHUB_TOKEN to a GitHub token with Administration: write permission for $Owner/$Repo."
}

$headers = @{
    Accept                 = "application/vnd.github+json"
    Authorization          = "Bearer $Token"
    "X-GitHub-Api-Version" = $ApiVersion
}

# Job names exactly as reported by the workflows.
$requiredChecks = @(
    "Validate",
    "Python coverage",
    "Secret scan (gitleaks)",
    "Dependency audit (Python)"
)

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
            strict   = $false
            contexts = $requiredChecks
        }
        enforce_admins                   = $false
        required_pull_request_reviews    = @{
            dismiss_stale_reviews           = $true
            require_code_owner_reviews      = $RequireCodeOwnerReview
            required_approving_review_count = $RequiredApprovals
            require_last_push_approval      = $false
        }
        restrictions                     = $null
        required_linear_history          = $false
        allow_force_pushes               = $false
        allow_deletions                  = $false
        block_creations                  = $false
        required_conversation_resolution = $true
        lock_branch                      = $false
        allow_fork_syncing               = $true
    }

    Write-Host "Applying branch protection to $Branch (approvals: $RequiredApprovals, code owners: $RequireCodeOwnerReview)..."
    Invoke-GitHubJson -Method Put -Uri $baseUri -Body $payload | Out-Null
}

Write-Host "Setting default branch to $DefaultBranch..."
Invoke-GitHubJson `
    -Method Patch `
    -Uri "https://api.github.com/repos/$Owner/$Repo" `
    -Body @{ default_branch = $DefaultBranch } | Out-Null

Protect-Branch -Branch "develop" -RequiredApprovals 0 -RequireCodeOwnerReview $false
Protect-Branch -Branch "dev" -RequiredApprovals 1 -RequireCodeOwnerReview $false
Protect-Branch -Branch "main" -RequiredApprovals 1 -RequireCodeOwnerReview $true

Write-Host "Default branch set to $DefaultBranch."
Write-Host "Branch protection applied for $Owner/$Repo on develop, dev and main."
