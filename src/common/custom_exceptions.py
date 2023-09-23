"""
    This module contains the list of all custom exceptions for Citadel IDP Backend
"""


class CitadelIDPBackendException(Exception):
    """
    Generic Citadel IDP Exception to be raised for any high level processing failures.
    """


class MissingConfigException(CitadelIDPBackendException):
    """
    Exception to be raised when some config is missing or empty.
    """


class MissingDocumentTypeException(CitadelIDPBackendException):
    """
    Exception to be raised when document type cannot be inferred from file name.
    """


class JobExecutionException(CitadelIDPBackendException):
    """
    Exception to be raised when a folder is expected to be present but doesn't exist.
    """
