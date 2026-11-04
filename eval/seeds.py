"""Seed questions from the PRD quick eval, with the expected outdated / still-true IDs."""

SEED_QUESTIONS = [
    {
        "question": "What do we know about checkout?",
        "as_of": "2026-07-15",
        "outdated": ["C054"],
        "resolved_by": ["R12-01"],
        "still_true": ["C070"],
    },
    {
        "question": "What are users' problems with search?",
        "as_of": "2026-05-15",
        "outdated": ["C019", "C034", "C046"],
        "resolved_by": ["R08-01", "R09-02"],
        "still_true": ["C052"],
    },
    {
        "question": "Can people use Tessera on mobile without a connection?",
        "as_of": "2026-06-30",
        "outdated": ["C035", "C048"],
        "resolved_by": ["R10-01"],
        "still_true": ["C060"],
    },
    {
        "question": "What do users think of the sidebar?",
        "as_of": "2026-09-01",
        "outdated": ["C008"],
        "resolved_by": ["R02-01", "R16-01"],
        "still_true": ["C014", "C061"],  # partial case: only partly resolved by R16-01
    },
    {
        "question": "What pain do developers have detecting database changes?",
        "as_of": "2026-10-20",
        "outdated": ["C087", "C097"],
        "resolved_by": ["R19-02", "R20-02"],
        "still_true": ["C096", "C098"],
    },
]
