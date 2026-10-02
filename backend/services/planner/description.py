"""Convert the planner's small formatting vocabulary to Calendar HTML and back."""
from html import escape
from html.parser import HTMLParser
import re


INLINE = re.compile(r'(\*\*[^*\n]+\*\*|\*[^*\n]+\*|<u>[^<\n]+</u>|\[[^\]\n]+\]\(https?://[^)\s]+\))')


def inline_html(value):
    result = []
    for part in INLINE.split(value):
        if part.startswith('**') and part.endswith('**'):
            result.append('<b>' + escape(part[2:-2]) + '</b>')
        elif part.startswith('*') and part.endswith('*'):
            result.append('<i>' + escape(part[1:-1]) + '</i>')
        elif part.startswith('<u>') and part.endswith('</u>'):
            result.append('<u>' + escape(part[3:-4]) + '</u>')
        elif match := re.fullmatch(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', part):
            result.append(f'<a href="{escape(match[2], quote=True)}">{escape(match[1])}</a>')
        else:
            result.append(escape(part))
    return ''.join(result)


def to_google(value):
    lines, result, list_type = (value or '').split('\n'), [], None
    for line in lines:
        match = re.match(r'^(\d+\.|•)\s+', line)
        wanted = ('ul' if match[1] == '•' else 'ol') if match else None
        if list_type != wanted:
            if list_type:
                result.append(f'</{list_type}>')
            if wanted:
                result.append(f'<{wanted}>')
            list_type = wanted
        result.append(f'<li>{inline_html(line[match.end():])}</li>' if match else inline_html(line) + '<br>')
    if list_type:
        result.append(f'</{list_type}>')
    return ''.join(result).removesuffix('<br>')


class DescriptionParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.lists, self.links = [], [], []
        self.skip = 0

    def newline(self):
        if self.parts and not self.parts[-1].endswith('\n'):
            self.parts.append('\n')

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.skip += 1
        if self.skip:
            return
        if tag in {'b', 'strong'}:
            self.parts.append('**')
        elif tag in {'i', 'em'}:
            self.parts.append('*')
        elif tag == 'u':
            self.parts.append('<u>')
        elif tag == 'br':
            self.parts.append('\n')
        elif tag in {'p', 'div'}:
            self.newline()
        elif tag in {'ul', 'ol'}:
            self.newline()
            self.lists.append([tag, 0])
        elif tag == 'li':
            self.newline()
            if self.lists:
                self.lists[-1][1] += 1
            self.parts.append(f'{self.lists[-1][1]}. ' if self.lists and self.lists[-1][0] == 'ol' else '• ')
        elif tag == 'a':
            href = dict(attrs).get('href', '')
            allowed = bool(re.match(r'^https?://[^\s]+$', href))
            self.links.append(href if allowed else '')
            if allowed:
                self.parts.append('[')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in {'b', 'strong'}:
            self.parts.append('**')
        elif tag in {'i', 'em'}:
            self.parts.append('*')
        elif tag == 'u':
            self.parts.append('</u>')
        elif tag in {'p', 'div', 'li', 'ul', 'ol'}:
            self.newline()
            if tag in {'ul', 'ol'} and self.lists:
                self.lists.pop()
        elif tag == 'a' and self.links:
            href = self.links.pop()
            if href:
                self.parts.append(f']({href})')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def from_google(value):
    parser = DescriptionParser()
    parser.feed(value or '')
    return ''.join(parser.parts).rstrip('\n')
