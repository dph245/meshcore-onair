"""Case-sensitive lookup in sorted, distinct identifiers."""
from bisect import bisect_left


def unique_prefix(keys, token):
    """Return the only matching key, or None for missing or ambiguous prefixes."""
    index = bisect_left(keys, token)
    if index == len(keys) or not keys[index].startswith(token):
        return None
    # All matches are contiguous. A second match immediately follows the first.
    if index + 1 < len(keys) and keys[index + 1].startswith(token):
        return None
    return keys[index]
