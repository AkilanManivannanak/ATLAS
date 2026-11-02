"""Small stable integer PRNG with named, checkpointable streams."""

from __future__ import annotations

import hashlib

_MASK_64 = (1 << 64) - 1
_GAMMA = 0x9E3779B97F4A7C15
_MIX_1 = 0xBF58476D1CE4E5B9
_MIX_2 = 0x94D049BB133111EB


def derive_stream_seed(master_seed: int, stream_name: str) -> int:
    if not isinstance(master_seed, int) or isinstance(master_seed, bool):
        raise TypeError("simulation seed must be an integer")
    if not isinstance(stream_name, str) or not stream_name.strip():
        raise ValueError("random stream name is required")
    data = f"atlas-rng-v1\0{master_seed}\0{stream_name}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(data).digest()[:8], "big")


class DeterministicRandomStream:
    """SplitMix64 stream; integer behavior is stable across Python versions."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= _MASK_64:
            raise ValueError("random stream seed must be an unsigned 64-bit integer")
        self._state = seed

    @property
    def state(self) -> int:
        return self._state

    @classmethod
    def from_state(cls, state: int) -> DeterministicRandomStream:
        return cls(state)

    def copy(self) -> DeterministicRandomStream:
        return DeterministicRandomStream(self._state)

    def next_uint64(self) -> int:
        self._state = (self._state + _GAMMA) & _MASK_64
        value = self._state
        value = ((value ^ (value >> 30)) * _MIX_1) & _MASK_64
        value = ((value ^ (value >> 27)) * _MIX_2) & _MASK_64
        return value ^ (value >> 31)

    def randbelow(self, upper_bound: int) -> int:
        if not isinstance(upper_bound, int) or isinstance(upper_bound, bool) or upper_bound <= 0:
            raise ValueError("upper_bound must be a positive integer")
        if upper_bound > 1 << 64:
            raise ValueError("upper_bound cannot exceed 2**64")
        threshold = (1 << 64) % upper_bound
        while True:
            value = self.next_uint64()
            if value >= threshold:
                return value % upper_bound
