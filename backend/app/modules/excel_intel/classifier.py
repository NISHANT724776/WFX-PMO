"""Sheet classification from headers, sheet name and layout. Returns (class, confidence)."""
from app.modules.excel_intel.profiler import SheetProfile, norm_header

# class -> list of (phrase, weight). A phrase matches if it is contained in any normalised header.
SIGNATURES: dict[str, list[tuple[str, float]]] = {
    "project_plan": [("project stage", 1.5), ("project milestone", 2.5), ("phase", 2), ("task", 2), ("activity", 1), ("start date", 1.5), ("end date", 1.5), ("duration", 1), ("actual start", 1), ("onsite", 1), ("responsible party", 1), ("dependencies", 1), ("resource", 0.5)],
    "milestone_matrix": [("events", 2), ("planned date", 2), ("actual date", 2), ("responsibility", 1), ("spoc", 1)],
    "gap_tracker": [("issue id", 2), ("event", 1), ("team", 0.5), ("module", 1), ("development scope", 1.5), ("description", 1), ("priority", 1), ("category", 0.5), ("solution", 1), ("spec", 1.5), ("proto", 1), ("specs created", 1)],
    "approval_signoff": [("department", 1.5), ("mapping date", 1.5), ("submission date", 1.5), ("sign off", 2), ("approval status", 1.5), ("target date", 1), ("status", 0.5)],
    "uat_scenarios": [("scenario id", 3), ("scenario", 1), ("expected result", 2), ("pre condition", 1.5), ("test data", 1.5), ("business objective", 1.5), ("functionality", 1)],
    "integration_register": [("partner", 2), ("system", 1), ("message", 1.5), ("technology", 1.5), ("direction", 1.5), ("region", 1), ("endpoint", 1.5), ("business domain", 1.5)],
    "reports_inventory": [("folder", 2), ("sub folder", 2), ("reports count", 3)],
    "delivery_schedule": [("customer release date", 3), ("specs responsibility", 2.5), ("testing responsibility", 2.5), ("dev initiation", 1.5), ("stream", 1), ("helpdesk", 1), ("handover to qa", 1.5), ("shahi tracker ref", 1)],
    "tech_tracker": [("tech owner", 3), ("qa owner", 3), ("product owner", 2), ("functional specs status", 2.5), ("specs discussion", 2), ("pd remarks", 1.5), ("meeting remarks", 1), ("target brd", 1.5)],
    "brd": [("brd", 2), ("key pointers", 2), ("covered in proto", 2), ("development phase", 1)],
    "helpdesk_brd": [("helpdesk id", 2.5), ("shahi tracker ref", 1.5), ("helpdesk description", 2.5), ("brd status", 1), ("category", 0.5)],
    "open_points": [("request date", 2.5), ("request from", 2.5), ("division", 2), ("status", 0.5)],
    "discussion": [("concern", 2.5), ("brd serial no", 2), ("functionality status", 2), ("document reference", 2), ("tracker sr no", 2)],
    "scope": [("scope as per brd", 3), ("feedback", 2), ("requirement", 1)],
    "dependency_register": [("pending", 1.5), ("revised target", 2), ("actual closure", 2), ("components", 1), ("responsibility", 1), ("target date", 1)],
    "wbs": [("wbs code", 3), ("level", 1), ("work package", 2), ("week start", 1.5), ("workstream", 1)],
}
SHEET_NAME_HINTS = {
    "project_plan": ("project plan", "detailed plan"), "gap_tracker": ("gap",), "approval_signoff": ("signoff", "sign off", "e2e", "blueprint"),
    "uat_scenarios": ("uat",), "integration_register": ("integration",), "reports_inventory": ("report",), "wbs": ("wbs",),
    "milestone_matrix": ("master", "tracker"), "delivery_schedule": ("delivery schedule",), "tech_tracker": ("tech",), "brd": ("brd",), "discussion": ("discussion",), "scope": ("scope",), "open_points": ("open points",),
}


def classify_sheet(name: str, profile: SheetProfile) -> tuple[str, float]:
    headers = [norm_header(c.header) for c in profile.columns]
    if not headers or profile.stats["data_rows"] == 0:
        return "unknown", 0.0
    # matrix layout: repeating sub-headers under group labels is decisive
    groups = {c.group_label for c in profile.columns if c.group_label}
    if len(groups) >= 2:
        return "milestone_matrix", 0.95
    lname = norm_header(name)
    best, best_score = "unknown", 0.0
    for cls, sig in SIGNATURES.items():
        total = sum(w for _, w in sig)
        hit = sum(w for phrase, w in sig if any(phrase in h for h in headers))
        score = hit / total
        if any(h in lname for h in SHEET_NAME_HINTS.get(cls, ())):
            score += 0.12
        if score > best_score:
            best, best_score = cls, score
    if best_score < 0.5 and profile.stats["data_rows"] <= 15 and len(profile.columns) <= 5 and not any(c.inferred_type == "date" for c in profile.columns):
        return "lookup", 0.7  # a small reference list, unless a known layout matched well
    if best_score < 0.35:
        return "unknown", round(best_score, 2)
    return best, round(min(best_score, 0.99), 2)
