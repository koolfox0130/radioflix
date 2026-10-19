"""Sanitized failures crossing the capture adapter boundary."""


class CaptureFailure(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class CaptureNotReady(CaptureFailure):
    def __init__(self):
        super().__init__('capture_not_ready')
