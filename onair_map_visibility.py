"""Geographic display policy only; never changes archive or radio identities."""
import re
from collections import defaultdict


class MapVisibility:
    def __init__(self, nodes, manual=()):
        types = {node['public_key'].lower(): node['node_type'] for node in nodes}
        keys = {key for key, kind in types.items() if kind == 2}
        keys.update(row['public_key'].lower() for row in manual
                    if types.get(row['public_key'].lower(), 2) == 2)
        self.repeater_keys = sorted(key for key in keys if re.fullmatch('[0-9a-f]{64}', key))
        prefixes = defaultdict(set)
        for key in self.repeater_keys:
            prefixes[key[:6]].add(key)
        self.collisions = {prefix for prefix, identities in prefixes.items() if len(identities) > 1}

    def hidden(self, key, node_type=2, prefix_bytes=None):
        return ((prefix_bytes is None or prefix_bytes <= 3) and node_type == 2
                and bool(key) and key[:6].lower() in self.collisions)
