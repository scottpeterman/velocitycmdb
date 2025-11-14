import re
import bleach
from bleach.css_sanitizer import CSSSanitizer


def process_internal_links(content):
    """
    Convert [[Note Title]] to <a href="/notes/123">Note Title</a>
    """
    from velocitycmdb.app.blueprints.notes.models import Note

    pattern = r'\[\[([^\]]+)\]\]'

    def replacer(match):
        title = match.group(1)
        note = Note.find_by_title(title)
        if note:
            return f'<a href="/notes/{note["id"]}" class="internal-link">{title}</a>'
        return f'<span class="broken-link" title="Note not found">{title}</span>'

    return re.sub(pattern, replacer, content)


def sanitize_svg(svg_content):
    """
    Remove dangerous elements from SVG uploads
    """
    allowed_tags = [
        'svg', 'path', 'rect', 'circle', 'ellipse', 'line',
        'polyline', 'polygon', 'text', 'tspan', 'g', 'defs',
        'use', 'clipPath', 'mask', 'pattern', 'linearGradient',
        'radialGradient', 'stop', 'title', 'desc'
    ]

    allowed_attrs = {
        '*': ['id', 'class', 'style', 'transform', 'fill',
              'stroke', 'stroke-width', 'opacity'],
        'svg': ['viewBox', 'width', 'height', 'xmlns', 'xmlns:xlink'],
        'path': ['d'],
        'rect': ['x', 'y', 'width', 'height', 'rx', 'ry'],
        'circle': ['cx', 'cy', 'r'],
        'ellipse': ['cx', 'cy', 'rx', 'ry'],
        'line': ['x1', 'y1', 'x2', 'y2'],
        'polyline': ['points'],
        'polygon': ['points'],
        'text': ['x', 'y', 'dx', 'dy', 'text-anchor'],
        'use': ['href', 'xlink:href', 'x', 'y'],
        'linearGradient': ['x1', 'y1', 'x2', 'y2', 'gradientUnits'],
        'radialGradient': ['cx', 'cy', 'r', 'fx', 'fy'],
        'stop': ['offset', 'stop-color', 'stop-opacity']
    }

    css_sanitizer = CSSSanitizer(
        allowed_css_properties=[
            'fill', 'stroke', 'stroke-width', 'opacity',
            'font-family', 'font-size', 'font-weight'
        ]
    )

    return bleach.clean(
        svg_content,
        tags=allowed_tags,
        attributes=allowed_attrs,
        css_sanitizer=css_sanitizer,
        strip=True
    )