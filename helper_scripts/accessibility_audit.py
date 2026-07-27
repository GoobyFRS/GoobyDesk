import os
import re
from html.parser import HTMLParser
from pathlib import Path

CSS_COLOR_RE = re.compile(r"(#(?:[0-9a-fA-F]{3,8})|rgba?\([^)]+\)|hsla?\([^)]+\))")


def parse_color(color):
    color = color.strip()
    if color.startswith('#'):
        hex_val = color[1:]
        if len(hex_val) == 3:
            hex_val = ''.join(2 * hex_char for hex_char in hex_val)
        if len(hex_val) == 6:
            red = int(hex_val[0:2], 16)
            green = int(hex_val[2:4], 16)
            blue = int(hex_val[4:6], 16)
            return (red, green, blue, 1)
        if len(hex_val) == 8:
            red = int(hex_val[0:2], 16)
            green = int(hex_val[2:4], 16)
            blue = int(hex_val[4:6], 16)
            alpha = int(hex_val[6:8], 16) / 255
            return (red, green, blue, alpha)
    if color.startswith('rgb(') or color.startswith('rgba('):
        parts = color[color.index('(')+1:color.index(')')].split(',')
        vals = [part.strip() for part in parts]
        red = int(vals[0])
        green = int(vals[1])
        blue = int(vals[2])
        alpha = float(vals[3]) if len(vals) == 4 else 1
        return (red, green, blue, alpha)
    return None


def luminance(red, green, blue):
    def chan(value):
        value = value / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * chan(red) + 0.7152 * chan(green) + 0.0722 * chan(blue)


def blend_over(fg, bg):
    fg_r, fg_g, fg_b, fg_a = fg
    bg_r, bg_g, bg_b, bg_a = bg
    out_a = fg_a + bg_a * (1 - fg_a)
    if out_a == 0:
        return (0, 0, 0, 0)
    out_r = (fg_r * fg_a + bg_r * bg_a * (1 - fg_a)) / out_a
    out_g = (fg_g * fg_a + bg_g * bg_a * (1 - fg_a)) / out_a
    out_b = (fg_b * fg_a + bg_b * bg_a * (1 - fg_a)) / out_a
    return (out_r, out_g, out_b, out_a)


def contrast_ratio(fg, bg):
    if fg[3] < 1:
        fg = blend_over(fg, bg)
    if bg[3] < 1:
        bg = blend_over(bg, (13, 17, 23, 1))
    L1 = luminance(*fg[:3])
    L2 = luminance(*bg[:3])
    lighter = max(L1, L2)
    darker = min(L1, L2)
    return (lighter + 0.05) / (darker + 0.05)


class TemplateParser(HTMLParser):
    def __init__(self, filename):
        super().__init__()
        self.filename = filename
        self.ids = []
        self.labels = []
        self.inputs = []
        self.imgs = []
        self.buttons = []
        self.anchors = []
        self.role_alert = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append((attrs['id'], self.getpos()))
        if tag == 'label':
            self.labels.append((attrs.get('for'), self.getpos()))
        if tag in ('input', 'textarea', 'select'):
            self.inputs.append((tag, attrs.get('id'), attrs.get('name'), attrs.get('type'), self.getpos()))
        if tag == 'img':
            self.imgs.append((attrs.get('src'), attrs.get('alt'), self.getpos()))
        if tag == 'button':
            self.buttons.append((attrs.get('type'), attrs.get('name'), attrs.get('aria-label'), self.getpos()))
        if tag == 'a':
            self.anchors.append((attrs.get('href'), attrs.get('role'), attrs.get('aria-label'), self.getpos()))
        if attrs.get('role') == 'alert':
            self.role_alert.append(self.getpos())

    def error(self, message):
        self.errors.append(message)


def scan_templates(root):
    problems = []
    for path in Path(root).rglob('*.html'):
        text = path.read_text(encoding='utf-8')
        parser = TemplateParser(path.name)
        parser.feed(text)
        ids = parser.ids
        dup = {identifier: [pos for value, pos in ids if value == identifier] for identifier in {value for value, _ in ids}}
        for ident, positions in dup.items():
            if ident and len(positions) > 1:
                problems.append((path, f'duplicate id "{ident}" found {len(positions)} times'))
        label_for_ids = {for_id for for_id, _ in parser.labels if for_id}
        input_ids = {id_ for _, id_, _, _, _ in parser.inputs if id_}
        for type_, id_, name, input_type, pos in parser.inputs:
            if id_ is None and input_type != 'hidden':
                problems.append((path, f'input/select/textarea missing id at {pos}'))
        for for_id, pos in parser.labels:
            if for_id and for_id not in input_ids:
                problems.append((path, f'label for="{for_id}" has no matching input id at {pos}'))
        for src, alt, pos in parser.imgs:
            if src and (not alt or alt.strip() == ''):
                problems.append((path, f'img missing alt text at {pos}'))
        for href, role, aria, pos in parser.anchors:
            if href and href.strip() == '#':
                problems.append((path, f'anchor with empty href at {pos}'))
    return problems


def scan_css(root):
    css_path = Path(root)
    text = css_path.read_text(encoding='utf-8')
    token = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    rule_re = re.compile(r'([^{}]+){([^}]+)}')
    vars = {}
    for match in rule_re.finditer(token):
        sel = match.group(1).strip()
        body = match.group(2)
        if sel == ':root':
            for decl in body.split(';'):
                if ':' in decl:
                    name, value = decl.split(':', 1)
                    vars[name.strip()] = value.strip()
    issues = []
    for selector_key, selector_value in vars.items():
        if selector_value.startswith('var('):
            ref = selector_value[4:-1].strip()
            vars[selector_key] = vars.get(ref, selector_value)
    # check badges and alerts for contrast
    selector_pairs = [('.badge-info', '#0d1117'), ('.badge-warning', '#0d1117'), ('.badge-success', '#0d1117'), ('.badge-secondary', '#0d1117'), ('.badge-danger', '#0d1117'), ('.badge-primary', '#0d1117'), ('.alert--danger', '#0d1117'), ('.flash.success', '#0d1117'), ('.flash.warning', '#0d1117'), ('.flash.info', '#0d1117')]
    css = {sel: {m.group(1).strip(): m.group(2).strip() for m in re.finditer(r'([\w-]+)\s*:\s*([^;]+);', body)} for sel, body in []}
    for sel, bg in selector_pairs:
        found = re.search(rf'{re.escape(sel)}\s*{{([^}}]+)}}', token)
        if found:
            decs = {name.strip(): value.strip() for name, value in re.findall(r'([\w-]+)\s*:\s*([^;]+);', found.group(1))}
            fg = parse_color(decs.get('color', '#ffffff'))
            bgc = parse_color(decs.get('background', bg))
            if fg and bgc and contrast_ratio(fg, bgc) < 4.5:
                issues.append((sel, fg, bgc, contrast_ratio(fg, bgc)))
    return issues


def main():
    root = Path(__file__).resolve().parent.parent
    template_problems = scan_templates(root / 'templates')
    css_issues = scan_css(root / 'static/styles.css')
    print('TEMPLATE PROBLEMS:')
    for p, msg in template_problems:
        print(f'{p.relative_to(root)}: {msg}')
    print('\nCSS CONTRAST ISSUES:')
    for sel, fg, bg, ratio in css_issues:
        print(f'{sel}: contrast {ratio:.2f} (fg={fg}, bg={bg})')

if __name__ == '__main__':
    main()
