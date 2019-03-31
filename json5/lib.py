# Copyright 2015 Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import math
import re
import sys
import unicodedata

from .parser import Parser


if sys.version_info[0] < 3:
    # pylint: disable=redefined-builtin
    str = unicode


def load(fp, encoding=None, cls=None, object_hook=None, parse_float=None,
         parse_int=None, parse_constant=None, object_pairs_hook=None):
    """Deserialize ``fp`` (a ``.read()``-supporting file-like object
    containing a JSON document) to a Python object."""

    s = fp.read()
    return loads(s, encoding=encoding, cls=cls, object_hook=object_hook,
                 parse_float=parse_float, parse_int=parse_int,
                 parse_constant=parse_constant,
                 object_pairs_hook=object_pairs_hook)


def loads(s, encoding=None, cls=None, object_hook=None, parse_float=None,
          parse_int=None, parse_constant=None, object_pairs_hook=None):
    """Deserialize ``s`` (a ``str`` or ``unicode`` instance containing a
    JSON5 document) to a Python object."""

    assert cls is None, 'Custom decoders are not supported'

    if sys.version_info[0] < 3:
        decodable_type = type('')
    else:
        decodable_type = type(b'')
    if isinstance(s, decodable_type):
        encoding = encoding or 'utf-8'
        s = s.decode(encoding)

    if not s:
        raise ValueError('Empty strings are not legal JSON5')
    parser = Parser(s, '<string>')
    ast, err, newpos = parser.parse()
    if err:
        raise ValueError(err)

    def _fp_constant_parser(s):
        return float(s.replace('Infinity', 'inf').replace('NaN', 'nan'))

    if object_pairs_hook:
        dictify = object_pairs_hook
    elif object_hook:
        dictify = lambda pairs: object_hook(dict(pairs))
    else:
        dictify = dict

    parse_float = parse_float or float
    parse_int = parse_int or int
    parse_constant = parse_constant or _fp_constant_parser

    return _walk_ast(ast, dictify, parse_float, parse_int, parse_constant)


def _walk_ast(el, dictify, parse_float, parse_int, parse_constant):
    if el == 'None':
        return None
    if el == 'True':
        return True
    if el == 'False':
        return False
    ty, v = el
    if ty == 'number':
        if v.startswith('0x') or v.startswith('0X'):
            return parse_int(v, base=16)
        elif '.' in v or 'e' in v or 'E' in v:
            return parse_float(v)
        elif 'Infinity' in v or 'NaN' in v:
            return parse_constant(v)
        else:
            return parse_int(v)
    if ty == 'string':
        return v
    if ty == 'object':
        pairs = []
        for key, val_expr in v:
            val = _walk_ast(val_expr, dictify, parse_float, parse_int,
                            parse_constant)
            pairs.append((key, val))
        return dictify(pairs)
    if ty == 'array':
        return [_walk_ast(el, dictify, parse_float, parse_int, parse_constant)
                for el in v]
    raise Exception('unknown el: ' + el)  # pragma: no cover


def dumps(obj, **kwargs):
    """Serialize ``obj`` to a JSON5-formatted ``str``."""

    assert kwargs.get('cls', None) is None, 'Custom encoders are not supported'

    if kwargs.get('check_circular', True):
        seen = set()
    else:
        seen = None
    return _dumps(obj, seen, **kwargs)


def dump(obj, fp, **kwargs):
    """Serialize ``obj`` to a JSON5-formatted stream to ``fp`` (a ``.write()``-
    supporting file-like object)."""

    s = dumps(obj, **kwargs)
    fp.write(str(s))


def _dumps(obj, seen, **kwargs):
    if obj is True:
        return u'true'
    if obj is False:
        return u'false'
    if obj == None:
        return u'null'

    t = type(obj)
    if t == type('') or t == type(u''):
        return _dump_str(obj, kwargs.get('ensure_ascii', True))
    if t is float:
        return _dump_float(obj, kwargs.get('allow_nan', True))
    if t is int:
        return str(obj)

    if seen is not None:
        i = id(obj)
        if i in seen:
            raise ValueError('Circular reference detected.')
        else:
            seen.add(i)

    indent = kwargs.get('indent', None)
    if indent is None:
        separators = kwargs.get('separators', (u', ', u': '))
    else:
        separators = kwargs.get('separators', (u',', u': '))
    if indent is not None:
        level = kwargs.get('level', 1)
        nl = '\n'
        if type(indent) == int:
            if indent > 0:
                indent = ' ' * indent
            else:
                indent = ''
    else:
        indent = ''
        level = 0
        nl = ''

    item_sep, kv_sep = separators
    indent_str = nl + indent * level
    if nl:
        end_str = ',' + nl + indent * (level - 1)
    else:
        end_str = nl + indent * (level - 1)

    item_sep += indent_str
    kwargs['level'] = level + 1

    # In Python3, we'd check if this was an abc.Mapping.
    # For now, just check for the attrs we need to iterate over the object.
    if hasattr(t, 'keys') and hasattr(t, '__getitem__'):
        return _dump_dict(obj, seen, item_sep, kv_sep, indent_str, end_str,
                          **kwargs)

    # In Python3, we'd check if this was an abc.Sequence.
    # For now, just check for the attrs we need to iterate over the object.
    if hasattr(t, '__getitem__') and hasattr(t, '__iter__'):
        return (u'[' + indent_str +
                item_sep.join([_dumps(el, seen, **kwargs) for el in obj]) +
                end_str + u']')

    return kwargs.get('default', _raise_type_error)(obj)


def _dump_dict(obj, seen, item_sep, kv_sep, indent_str, end_str, **kwargs):
    if kwargs.get('sort_keys', False):
        keys = sorted(obj.keys())
    else:
        keys = obj.keys()

    s = u'{' + indent_str

    skipkeys = kwargs.get('skipkeys', False)
    ensure_ascii = kwargs.get('ensure_ascii', True)
    for i, k in enumerate(keys):
        valid_key, key_str = _dumpkey(k, ensure_ascii)
        if valid_key:
            s += key_str + kv_sep + _dumps(obj[k], seen, **kwargs)
            if i < len(keys) - 1:
                s += item_sep
        elif skipkeys:
            continue
        else:
            raise TypeError('invalid key %s' % str(k))
    s += end_str + u'}'
    return s


def _dump_float(obj, allow_nan):
    allow_nan = kwargs.get('allow_nan', True)
    if allow_nan:
        if math.isnan(obj):
            return 'NaN'
        if obj == float('inf'):
            return 'Infinity'
        if obj == float('-inf'):
            return '-Infinity'
    elif math.isnan(obj) or obj == float('inf') or obj == float('-inf'):
        raise ValueError('Out of range float values '
                         'are not JSON compliant')
    return str(obj)


def _dumpkey(k, ensure_ascii):
    if type(k) in (int, float, type(''), long, type(u'')) or k == None:
        if _is_ident(k) and not _is_reserved_word(k):
            return True, k
        return True, _dump_str(k, ensure_ascii)
    return False, ''


def _dump_str(obj, ensure_ascii):
    ret = ['"']
    for ch in obj:
        if ch == '\\':
            ret.append('\\\\')
        elif ch == '"':
            ret.append('\\"')
        elif ch == u'\u2028':
            ret.append('\\u2028')
        elif ch == u'\u2029':
            ret.append('\\u2029')
        elif ch == '\n':
            ret.append('\\n')
        elif ch == '\r':
            ret.append('\\r')
        elif ch == '\b':
            ret.append('\\b')
        elif ch == '\f':
            ret.append('\\f')
        elif ch == '\t':
            ret.append('\\t')
        elif ch == '\v':
            ret.append('\\v')
        elif ch == '\0':
            ret.append('\\0')
        elif not ensure_ascii:
            ret.append(ch)
        else:
            o = ord(ch)
            if o >= 32 and o < 128:
                ret.append(ch)
            elif ord(ch) < 65536:
                ret.append('\u' + '%04x' % ord(ch))
            else:
                val = ord(ch) - 0x10000
                high = 0xd800 + val >> 10
                low = 0xdc00 + val & 0x3ff
                ret.append('\\u%04x\\u%04x' % (high, low))
    return u''.join(ret) + '"'


def _is_ident(k):
    k = str(k)
    if not _is_id_start(k[0]) and k[0] not in (u'$', u'_'):
        return False
    for ch in k[1:]:
        if not _is_id_continue(ch) and ch not in (u'$', u'_'):
            return False
    return True

def _is_id_start(ch):
    return unicodedata.category(ch) in (
        'Lu', 'Ll', 'Li', 'Lt', 'Lm', 'Lo', 'Nl')


def _is_id_continue(ch):
    return unicodedata.category(ch) in (
        'Lu', 'Ll', 'Li', 'Lt', 'Lm', 'Lo', 'Nl', 'Nd', 'Mn', 'Mc', 'Pc')


_reserved_word_re = None

def _is_reserved_word(k):
    global _reserved_word_re

    if _reserved_word_re is None:
        # List taken from section 7.6.1 of ECMA-262.
        _reserved_word_re = re.compile('|'.join([
            'break',
            'case',
            'catch',
            'class',
            'const',
            'continue',
            'debugger',
            'default',
            'delete',
            'do',
            'else',
            'enum',
            'export',
            'extends',
            'false',
            'finally',
            'for',
            'function',
            'if',
            'import',
            'in',
            'instanceof',
            'new',
            'null',
            'return',
            'super',
            'switch',
            'this',
            'throw',
            'true',
            'try',
            'typeof',
            'var',
            'void',
            'while',
            'with',
        ]))
    return _reserved_word_re.match(k) is not None


def _raise_type_error(obj):
    raise TypeError('%s is not JSON5 serializable' % repr(obj))
