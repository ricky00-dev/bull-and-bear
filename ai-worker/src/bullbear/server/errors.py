class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, reasons=None):
        self.status, self.code, self.message = status, code, message
        self.reasons = reasons
