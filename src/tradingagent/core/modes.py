from enum import StrEnum


class Mode(StrEnum):
    BACKTEST = "BACKTEST"
    REPLAY = "REPLAY"
    PAPER = "PAPER"
    LIVE = "LIVE"


class Stage(StrEnum):
    S0 = "S0"
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"


class DayState(StrEnum):
    BOOT = "BOOT"
    PRE_MARKET = "PRE_MARKET"
    OPEN_OBSERVE = "OPEN_OBSERVE"
    ACTIVE_HUNT = "ACTIVE_HUNT"
    IN_POSITION = "IN_POSITION"
    WIND_DOWN = "WIND_DOWN"
    SQUARE_OFF = "SQUARE_OFF"
    POST_MARKET = "POST_MARKET"
    HALTED = "HALTED"
    CLOSED = "CLOSED"


# DESIGN.md A3: stage and mode must agree.
VALID_STAGE_MODES: dict[Stage, set[Mode]] = {
    Stage.S0: {Mode.PAPER},
    Stage.S1: {Mode.PAPER},
    Stage.S2: {Mode.LIVE},
    Stage.S3: {Mode.LIVE},
}
