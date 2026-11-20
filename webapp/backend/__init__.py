"""get_backend(): the one backend instance, picked by BACKEND in .env (fake | aws)."""

import config

_backend = None


def get_backend():
    global _backend
    if _backend is None:
        if config.BACKEND == "aws":
            from .aws import AwsBackend
            _backend = AwsBackend()
        else:
            from .fake import FakeBackend
            _backend = FakeBackend()
    return _backend
