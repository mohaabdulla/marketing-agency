"""Connector abstraction exceptions for LEXNIS Marketing Agency."""


class ConnectorError(Exception):
    pass


class AuthenticationError(ConnectorError):
    pass


class QuotaExceededError(ConnectorError):
    pass


class PermissionDeniedError(ConnectorError):
    pass

