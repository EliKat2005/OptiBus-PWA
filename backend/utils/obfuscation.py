"""
OptiBus ID Obfuscation — DevSecOps v5.0
Ofuscación de IDs autoincrementables con XOR + base62.
Evita que la competencia enumere recursos iterando del 1 al 1000.
"""

import hashlib
import os

_salt = os.getenv("OPTIBUS_API_KEY", "optibus-default-salt")
_salt_hash = hashlib.sha256(_salt.encode()).hexdigest()[:16]
_MIN_LENGTH = 8
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_BASE = len(_ALPHABET)


def encode_id(entity_id: int) -> str:
    """Codifica un ID entero a un hash opaco de 8+ caracteres."""
    n = entity_id ^ int(_salt_hash, 16)
    result = []
    while n > 0:
        result.append(_ALPHABET[n % _BASE])
        n //= _BASE
    while len(result) < _MIN_LENGTH:
        pad_idx = (entity_id * 7 + len(result)) % _BASE
        result.append(_ALPHABET[pad_idx])
    return "".join(reversed(result))


def decode_id(obfuscated: str) -> int:
    """Decodifica un hash opaco de vuelta al ID entero original."""
    n = 0
    for char in obfuscated:
        if char in _ALPHABET:
            n = n * _BASE + _ALPHABET.index(char)
    return n ^ int(_salt_hash, 16)