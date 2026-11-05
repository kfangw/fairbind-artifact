"""Load scenario YAML with PyYAML when installed, otherwise with a small parser.

The fallback covers the block subset used in experiments/scenarios: nested
mappings, lists of scalars, plain, single-quoted and double-quoted scalars.
It rejects anchors, tags, flow collections other than [] and {}, and
multi-line scalars.
"""
import json
import re

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - depends on the environment
    _yaml = None

_INT = re.compile(r'^[-+]?[0-9]+$')
_FLOAT = re.compile(r'^[-+]?([0-9]+\.[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?$')


def load(text):
    if _yaml is not None:
        return _yaml.safe_load(text)
    return parse_subset(text)


def scalar(raw):
    raw = raw.strip()
    if raw.startswith("'"):
        if len(raw) < 2 or not raw.endswith("'"):
            raise ValueError(f'unterminated quoted scalar: {raw}')
        return raw[1:-1].replace("''", "'")
    if raw.startswith('"'):
        return json.loads(raw)
    if raw in ('[]', '{}'):
        return [] if raw == '[]' else {}
    if raw[:1] in '[{&*!|>%@`':
        raise ValueError(f'unsupported YAML construct: {raw}')
    if raw in ('true', 'True', 'TRUE'):
        return True
    if raw in ('false', 'False', 'FALSE'):
        return False
    if raw in ('null', 'Null', 'NULL', '~', ''):
        return None
    if _INT.match(raw):
        return int(raw)
    if _FLOAT.match(raw):
        return float(raw)
    if ' #' in raw:
        raise ValueError(f'comments after values are not supported: {raw}')
    return raw


def _split_key(content):
    if content.startswith(("'", '"')):
        raise ValueError('quoted keys are not supported')
    if content.endswith(':'):
        return content[:-1], ''
    key, sep, rest = content.partition(': ')
    if not sep:
        raise ValueError(f'expected "key: value": {content}')
    return key, rest


def parse_subset(text):
    lines = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if '\t' in line[:len(line) - len(line.lstrip())]:
            raise ValueError(f'line {number}: tab indentation')
        indent = len(line) - len(line.lstrip(' '))
        lines.append((indent, line.strip(), number))
    if not lines:
        return None
    value, pos = _block(lines, 0, lines[0][0])
    if pos != len(lines):
        raise ValueError(f'line {lines[pos][2]}: unexpected indentation')
    return value


def _block(lines, pos, indent):
    if lines[pos][1].startswith('- ') or lines[pos][1] == '-':
        return _list(lines, pos, indent)
    return _mapping(lines, pos, indent)


def _list(lines, pos, indent):
    out = []
    while pos < len(lines) and lines[pos][0] == indent and (lines[pos][1].startswith('- ') or lines[pos][1] == '-'):
        item = lines[pos][1][2:]
        if item.startswith('- ') or (': ' in item and not item.startswith(("'", '"'))) or item.endswith(':'):
            raise ValueError(f'line {lines[pos][2]}: only scalar list items are supported')
        out.append(scalar(item))
        pos += 1
    return out, pos


def _mapping(lines, pos, indent):
    out = {}
    while pos < len(lines):
        ind, content, number = lines[pos]
        if ind < indent:
            break
        if ind > indent:
            raise ValueError(f'line {number}: unexpected indentation')
        if content.startswith('- '):
            break
        key, rest = _split_key(content)
        if key in out:
            raise ValueError(f'line {number}: duplicate key {key}')
        pos += 1
        if rest.strip():
            out[key] = scalar(rest)
            continue
        if pos < len(lines) and lines[pos][1].startswith('- ') and lines[pos][0] >= indent:
            out[key], pos = _list(lines, pos, lines[pos][0])
        elif pos < len(lines) and lines[pos][0] > indent:
            out[key], pos = _mapping(lines, pos, lines[pos][0])
        else:
            out[key] = None
    return out, pos
