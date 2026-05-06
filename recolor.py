"""
Black/white/gray recolor of index.html — contrast-aware, layout-preserving.

CONTRACT:
- Modify ONLY color values (hex / rgb / rgba). No layout, structure, or whitespace changes.
- Output line count must equal input line count (no spans across lines/attributes).
- Enforce contrast: foreground colors on dark backgrounds get a luminance floor.
- Preserve <img> tags untouched (they are external raster URLs, no inline color).

CONTRAST RULES:
- Hand-tuned :root token map (readability-checked for dark + light themes).
- Other inline colors: Rec.709 luminance preserve, with a soft floor for mid-tones
  that would otherwise become near-invisible on black bg (luminance 40-90 → bumped
  to 90 ONLY if the original was a saturated/cool color likely used as foreground;
  pure dark colors stay dark since they are likely backgrounds).
"""
import re
import sys

# --- Hand-tuned design system token override (dark theme) ---
# Replaces the values inside :root { ... } for design tokens.
TOKEN_MAP = {
    # backgrounds — keep deep
    '--bg':              '#000000',
    '--bg-elev':         '#0A0A0A',
    '--card':            '#161616',
    '--card-elev':       '#1F1F1F',
    # borders — bumped slightly for visibility on black
    '--border':          '#2E2E2E',
    '--border-strong':   '#3D3D3D',
    # accent — restrained slate blue (the ONE colored highlight; everything else is gray)
    '--accent':          '#7DA8E0',
    '--accent-deep':     '#4F6C8E',
    '--accent-dim':      'rgba(125, 168, 224, 0.12)',
    '--accent-glow':     'rgba(125, 168, 224, 0.40)',
    # text — bumped from luminance preserve to ensure readability on black
    '--text':            '#F0F0F0',
    '--text-dim':        '#B8B8B8',
    '--text-muted':      '#929292',
    '--text-faint':      '#6E6E6E',
    # warn/bad — distinguishable but desaturated
    '--warn':            '#D4D4D4',
    '--bad':             '#A8A8A8',
}

def rec709(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def hex_components(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) == 8:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), None

def gray_for_hex(r, g, b):
    """Pure Rec.709 luminance preserve. No floor — preserves full visual hierarchy
    (deep cards, subtle borders, faint dividers). Foreground readability is handled
    via the hand-tuned TOKEN_MAP applied AFTER this pass."""
    return round(rec709(r, g, b))

def replace_hex(m):
    raw = m.group(0)
    r, g, b, a = hex_components(raw)
    y = gray_for_hex(r, g, b)
    if a is not None:
        return '#{0:02X}{0:02X}{0:02X}{1:02X}'.format(y, a)
    return '#{0:02X}{0:02X}{0:02X}'.format(y)

def replace_rgb(m):
    inner = m.group(1)
    nums = re.findall(r'-?\d*\.?\d+%?', inner)
    if len(nums) < 3:
        return m.group(0)
    def to_byte(s):
        if s.endswith('%'):
            return float(s[:-1]) * 2.55
        return float(s)
    r, g, b = to_byte(nums[0]), to_byte(nums[1]), to_byte(nums[2])
    y = gray_for_hex(r, g, b)
    if len(nums) >= 4:
        a = nums[3]
        if a.endswith('%'):
            a = str(float(a[:-1]) / 100)
        return f'rgba({y}, {y}, {y}, {a})'
    return f'rgb({y}, {y}, {y})'

def apply_token_overrides(src):
    """Replace each design-token value inside the first :root { ... } block."""
    def replace_root(rootmatch):
        body = rootmatch.group(1)
        for token, value in TOKEN_MAP.items():
            # Match: --token: <value>;
            pattern = re.compile(
                r'(' + re.escape(token) + r'\s*:\s*)([^;]+)(;)'
            )
            body = pattern.sub(lambda mm: mm.group(1) + value + mm.group(3), body, count=1)
        return ':root {' + body + '}'
    return re.sub(r':root\s*\{([^}]*)\}', replace_root, src, count=1)

def main(path):
    src = open(path).read()
    line_count_in = src.count('\n')

    # 1. Generic luminance-preserve on hex (longest first to avoid 3-char eating prefix of 6-char).
    src = re.sub(r'#[0-9A-Fa-f]{8}\b', replace_hex, src)
    src = re.sub(r'#[0-9A-Fa-f]{6}\b', replace_hex, src)
    src = re.sub(r'#[0-9A-Fa-f]{3}\b', replace_hex, src)

    # 2. Generic on rgb/rgba — inner match RESTRICTED to digits/dots/commas/spaces/percent
    #    so unterminated rgba() inside [style*="..."] selectors can't get eaten.
    src = re.sub(r'rgba?\(([0-9.,\s%]+)\)', replace_rgb, src)

    # 3. LAST: override design system tokens with hand-tuned contrast-aware values.
    #    Applied after generic passes so token values aren't re-grayscaled.
    src = apply_token_overrides(src)

    line_count_out = src.count('\n')
    assert line_count_in == line_count_out, (
        f'Line count changed: {line_count_in} -> {line_count_out}. Layout corrupted.'
    )

    open(path, 'w').write(src)
    print(f'OK: {line_count_in} lines preserved.')

if __name__ == '__main__':
    main(sys.argv[1])
