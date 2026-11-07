# Evals

`questions.json` holds 32 questions: the brief's examples (b*), questions that use the
structured fields (f*), messy real-user phrasing (u*), ones that must be refused (n*, u10, u11,
g1), harder charts (x*), multi-step questions (m*, t1) and one whole-registry question (r1).
Each has `expect: answered | refused`.

With the service running on port 8765:

    uv run python evals/run_evals.py                       # all questions -> evals/report.json
    uv run python evals/run_evals.py --only=b3,m1          # a subset

For every answer it checks the outcome matches `expect`, the counts are consistent with the
trials analysed, every citation's excerpt is in the saved trial record, and (for phase,
status and sponsor-class bars) recounts the top two bars straight from the ClinicalTrials.gov API.
