"""Payment provider integrations."""

class PaymentProviderError(Exception):
    """Base error for payment providers."""


class PaymentProviderConfigurationError(PaymentProviderError):
    """Raised when provider configuration is invalid or missing."""


class PaymentProviderTransientError(PaymentProviderError):
    """A timeout, rate limit, or server failure may succeed on retry."""


class PaymentProviderPermanentError(PaymentProviderError):
    """A rejected request should be corrected before retrying."""

