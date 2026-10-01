class TradingAgentError(Exception):
    """Base for all internal errors."""


class ConfigError(TradingAgentError):
    pass


class BrokerError(TradingAgentError):
    pass


class BrokerAuthError(BrokerError):
    pass


class BrokerRateLimited(BrokerError):
    pass


class BrokerRejected(BrokerError):
    pass


class BrokerUnavailable(BrokerError):
    pass
