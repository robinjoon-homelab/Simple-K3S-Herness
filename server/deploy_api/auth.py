import hashlib
import threading
import time

from .errors import ApiError


class TokenVerifier:
    def __init__(self, github, ttl=300, clock=time.monotonic):
        self._github = github
        self._ttl = ttl
        self._clock = clock
        self._verified = {}
        self._lock = threading.Lock()

    def verify(self, authorization):
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(401, "unauthenticated", "Send a GitHub token as 'Authorization: Bearer <token>'.")
        token = authorization[len("Bearer "):].strip()
        if not token:
            raise ApiError(401, "unauthenticated", "Send a GitHub token as 'Authorization: Bearer <token>'.")
        key = hashlib.sha256(token.encode()).hexdigest()
        now = self._clock()
        with self._lock:
            if self._verified.get(key, 0) > now:
                return token
        self._github.get_user(token)
        with self._lock:
            self._verified[key] = now + self._ttl
        return token
