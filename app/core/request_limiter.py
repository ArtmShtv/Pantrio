import time


class TokenBucket:
    def __init__(self, capacity: int, sec_per_token: float):
        self.capacity = capacity
        self.sec_per_token = sec_per_token
        self.tokens = capacity
        self.last_refill = time.monotonic()


    def _refill(self) -> None:
        now = time.monotonic()
        new_tokens = int((now - self.last_refill) // self.sec_per_token)

        if new_tokens <= 0:
            return
        
        self.tokens = min(self.capacity, self.tokens + new_tokens)

        if self.tokens == self.capacity:
            self.last_refill = now
        else:
            self.last_refill += new_tokens * self.sec_per_token


    def allow(self) -> bool:
        self._refill()
        if self.tokens > 0:
            self.tokens -= 1
            return True
        return False


class RequestLimiter:
    def __init__(self, capacity: int, per_seconds: float):
        self.capacity = capacity
        self.sec_per_token = per_seconds / capacity
        self.buckets: dict[str, TokenBucket] = {}


    def allow(self, email: str) -> bool:
        bucket = self.buckets.get(email)
        if bucket is None:
            bucket = self.buckets[email] = TokenBucket(self.capacity, self.sec_per_token)
        return bucket.allow()