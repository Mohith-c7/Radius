// How the 0-100 confidence score should be presented. Until calibration
// (CA-*) ships the API reports "heuristic_uncalibrated"; unknown or missing
// kinds (older API versions) fall back to the same safe wording.
export const DEFAULT_SCORE_KIND = "heuristic_uncalibrated";

export function scoreKindLabel(kind?: string | null): {
  short: string;
  tooltip: string;
} {
  if (kind === "calibrated") {
    return {
      short: "Calibrated score",
      tooltip: "Calibrated confidence score.",
    };
  }
  return {
    short: "Uncalibrated heuristic",
    tooltip:
      "Uncalibrated heuristic score (0-100) built from fixed penalties. It is not a probability that the change is correct.",
  };
}
