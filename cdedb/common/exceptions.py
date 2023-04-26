#!/usr/bin/env python3

"""Custom exceptions for the CdEDB."""
from typing import Any

import werkzeug.exceptions


class QuotaException(werkzeug.exceptions.TooManyRequests):
    """
    Exception for signalling a quota excess. This is thrown in
    :py:mod:`cdedb.backend.cde` and caught in
    :py:mod:`cdedb.frontend.application`. We use a custom class so that
    we can distinguish it from other exceptions.
    """


class PrivilegeError(RuntimeError):
    """
    Exception for signalling missing privileges. This Exception is thrown by the
    backend to indicate an unprivileged call to a backend function. However,
    this situation should be prevented by privilege checks in the frontend.
    Thus, we typically consider this Exception as an unexpected programming
    error. In some cases the frontend may catch and handle the exception
    instead of preventing it in the first place.
    """
    def __init__(self, msg: str = "Not privileged", *args: Any):  # pylint: disable=keyword-arg-before-vararg
        super().__init__(msg, *args)


class APITokenError(PrivilegeError):
    """
    Special type of privilege error only raised by trying to access an API with an
    invalid or unknown key.
    """


class ArchiveError(RuntimeError):
    """
    Exception for signalling an exact error when archiving a persona
    goes awry.
    """


class PartialImportError(RuntimeError):
    """Exception for signalling a checksum mismatch in the partial import.

    Making this an exception rolls back the database transaction.
    """


class ValidationWarning(Exception):
    """Exception which should be suppressable by the user."""
