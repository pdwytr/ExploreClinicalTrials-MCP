"""Failures the workflow reports to the user. Each maps to an ErrorResponse code."""

from typing import Any

from cheiron.models.response import ErrorResponse


class WorkflowError(Exception):
    code = "internal_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(error=self.code, message=self.message, details=self.details)


class UnsupportedQuery(WorkflowError):
    """The question cannot be turned into a valid search or chart."""

    code = "unsupported_query"


class NoResults(WorkflowError):
    """The search ran but matched no trials."""

    code = "no_results"


class InvalidSearch(WorkflowError):
    """The API rejected a search the planner wrote (e.g. bad Essie syntax).
    The workflow feeds this back to the planner once before giving up."""

    code = "unsupported_query"


class UpstreamError(WorkflowError):
    """ClinicalTrials.gov or the LLM provider failed."""

    code = "upstream_error"
