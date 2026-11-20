// Pure helpers for the Settings page (CI upload setup). Unit tested.

export const UPLOAD_KEY_SCOPE = "ci-upload";
export const GITHUB_API_URL_VAR = "RADIUS_API_URL";
export const GITHUB_ORG_SECRET = "RADIUS_ORG_ID";
export const GITHUB_KEY_SECRET = "RADIUS_API_KEY";

/**
 * The API origin the upload action needs (it appends /api/v1 itself), derived
 * from the configured base URL. Returns "" for anything that is not http(s).
 */
export function ciApiUrl(base: string | null | undefined): string {
  const raw = (base ?? "").trim();
  if (!raw) return "";
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return "";
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return "";
  const path = url.pathname.replace(/\/+$/, "").replace(/\/api\/v1$/, "");
  return `${url.origin}${path}`;
}

/** The versioned endpoint shown to users, e.g. https://example.test/api/v1. */
export function ciUploadEndpoint(base: string | null | undefined): string {
  const api = ciApiUrl(base);
  return api ? `${api}/api/v1` : "";
}

/** A GitHub Actions workflow that runs pytest and uploads the JUnit XML to Radius. */
export function uploadWorkflowSnippet(): string {
  return [
    "name: tests",
    "on:",
    "  pull_request:",
    "",
    "permissions:",
    "  contents: read",
    "",
    "jobs:",
    "  test:",
    "    runs-on: ubuntu-latest",
    "    steps:",
    "      - uses: actions/checkout@v4",
    "        with:",
    "          ref: ${{ github.event.pull_request.head.sha }}",
    "      - run: pip install -r requirements.txt pytest",
    "      - run: pytest --junitxml=junit.xml",
    "      - name: Upload results to Radius",
    "        if: ${{ !cancelled() }}",
    "        # Pin to a full commit SHA in production.",
    "        uses: Mohith-c7/Radius/actions/upload-results@develop",
    "        with:",
    `          api-url: \${{ vars.${GITHUB_API_URL_VAR} }}`,
    `          organization-id: \${{ secrets.${GITHUB_ORG_SECRET} }}`,
    `          api-key: \${{ secrets.${GITHUB_KEY_SECRET} }}`,
    "          junit-path: junit.xml",
    "",
  ].join("\n");
}
