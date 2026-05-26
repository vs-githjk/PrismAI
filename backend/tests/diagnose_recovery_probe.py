"""Probe the production recovery parser against every malformation shape we've
observed. Run from any cwd.

Confirms which malformations the existing `_parse_function_tags` already handles
and which ones leak through to the "retrying without tools" branch.
"""
import re
import json


_FUNCTION_TAG_RE = re.compile(r"<function\s*=\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*", re.IGNORECASE)


def _find_matching_brace(s: str, start: int) -> int:
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _parse_function_tags(text: str) -> list[dict]:
    if not text:
        return []
    out = []
    pos = 0
    while pos < len(text):
        m = _FUNCTION_TAG_RE.search(text, pos)
        if not m:
            break
        name = m.group(1)
        body_start = m.end()
        while body_start < len(text) and text[body_start].isspace():
            body_start += 1
        if body_start < len(text) and text[body_start] == "{":
            body_end = _find_matching_brace(text, body_start)
            if body_end == -1:
                pos = m.end()
                continue
            args_str = text[body_start:body_end]
            try:
                json.loads(args_str)
            except json.JSONDecodeError:
                args_str = "{}"
            pos = body_end
        else:
            args_str = "{}"
            pos = body_start if body_start > m.end() else m.end()
        out.append({"name": name, "arguments": args_str})
    return out


def recover(text: str, valid: set) -> list[dict]:
    return [c for c in _parse_function_tags(text) if c["name"] in valid]


SAMPLES = [
    ("LOCAL_A (no >, space)",   '<function=web_search {"query": "X"} </function>'),
    ("LOCAL_B (no >, no space)", '<function=web_search{"query": "X"}</function>'),
    ("PROD (name:_prefix)",     '<function=name:"web_search" >{"query": "X"} </function>'),
    ("PROD (params= form)",     '<function=name:"web_search" parameters={"query": "X"}</function>'),
    ("PROD (params \"form)",    '<function=name:"web_search" parameters \'{"query": "X"}\'</function>'),
    ("GOOD (canonical)",        '<function=web_search>{"query": "X"}</function>'),
]


def main():
    valid = {"web_search", "gmail_send"}
    print(f"{'shape':30s} {'recovered?':12s} {'parsed':60s}")
    print("-" * 110)
    for label, text in SAMPLES:
        parsed = _parse_function_tags(text)
        rec = recover(text, valid)
        ok = "YES" if rec else "no"
        print(f"{label:30s} {ok:12s} {str(parsed)[:60]:60s}")


if __name__ == "__main__":
    main()
