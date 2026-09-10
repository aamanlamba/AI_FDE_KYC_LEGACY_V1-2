class ReviewNotFoundError(LookupError):
    """No review case exists with the given review_id."""


class ReviewNotEligibleError(RuntimeError):
    """The target case's decision does not permit opening an ordinary review case."""


class InvalidTransitionError(RuntimeError):
    """The requested status transition is not allowed from the review's current state."""
