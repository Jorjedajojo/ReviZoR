"""English UI strings for ReviZoR FranK. All user-facing text lives here."""

STRINGS: dict = {
    # ── App chrome ────────────────────────────────────────────────────────────
    "app_name":             "ReviZoR FranK",
    "app_tagline":          "AI-Powered CV Optimization Engine",
    "status_online":        "Online — AI Enhanced",
    "status_offline":       "Offline — Rule-Based Mode",
    "status_syncing":       "Syncing with AI...",

    # ── Upload stage ──────────────────────────────────────────────────────────
    "upload_header":        "Upload Your CV",
    "upload_instruction":   "Supported formats: PDF, DOCX, TXT",
    "upload_jd_label":      "Job Description (optional)",
    "upload_jd_help":       "Paste a job description to tailor your CV and get a match score.",
    "upload_jd_placeholder":"Paste the full job description here...",
    "upload_btn":           "Analyze & Optimize",
    "upload_both_label":    "Generate both General ATS and JD-Tailored outputs",
    "upload_both_help":     "Always enabled when a Job Description is provided.",

    # ── Processing ────────────────────────────────────────────────────────────
    "parsing_cv":           "Parsing CV...",
    "analyzing_ats":        "Running ATS analysis...",
    "optimizing_offline":   "Applying rule-based optimization...",
    "optimizing_ai":        "Requesting AI optimization from Claude...",
    "generating_linkedin":  "Generating LinkedIn profile...",
    "done":                 "Done!",

    # ── ATS report ────────────────────────────────────────────────────────────
    "ats_score_label":      "ATS Score",
    "ats_grade_label":      "Grade",
    "ats_issues_label":     "Issues Found",
    "ats_keyword_label":    "Keyword Match",
    "ats_sections_label":   "Sections",
    "ats_missing_label":    "Missing",
    "severity_critical":    "Critical",
    "severity_warning":     "Warning",
    "severity_info":        "Info",

    # ── Results tabs ──────────────────────────────────────────────────────────
    "tab_general":          "General ATS Output",
    "tab_jd_tailored":      "JD-Tailored Output",
    "tab_linkedin":         "LinkedIn Profile",
    "tab_download":         "Download",

    # ── Template selector ─────────────────────────────────────────────────────
    "template_label":       "Choose a Template",
    "template_best_for":    "Best for",
    "template_ats_badge":   "ATS Safe",

    # ── LinkedIn ──────────────────────────────────────────────────────────────
    "li_headline":          "Headline",
    "li_about":             "About / Summary",
    "li_experience":        "Experience",
    "li_skills":            "Skills",
    "li_education":         "Education",
    "li_certifications":    "Licenses & Certifications",
    "li_copy_hint":         "Click in the box below, select all (Ctrl+A), then copy (Ctrl+C) and paste directly into LinkedIn.",

    # ── Downloads ────────────────────────────────────────────────────────────
    "download_header":      "Download Your Optimized CV",
    "dl_word":              "Word (.docx)",
    "dl_odt":               "OpenDocument (.odt)",
    "dl_pdf":               "PDF (.pdf)",
    "dl_png":               "Image (.png)",
    "dl_txt":               "Plain Text (.txt)",
    "dl_linkedin":          "LinkedIn Copy-Paste (.txt)",
    "dl_all_general":       "Download All — General",
    "dl_all_jd":            "Download All — JD-Tailored",

    # ── Sync ─────────────────────────────────────────────────────────────────
    "sync_queued":          "Processed offline. Will enhance with AI when connection is restored.",
    "sync_enhanced":        "AI enhancement applied from queued session.",

    # ── Errors ───────────────────────────────────────────────────────────────
    "err_no_file":          "Please upload a CV file to continue.",
    "err_parse_failed":     "Could not parse the uploaded file. Please try PDF or DOCX format.",
    "err_api_failed":       "Claude API call failed. Falling back to offline optimization.",
    "err_export_failed":    "Export failed for format: {fmt}. Please try again.",
}
