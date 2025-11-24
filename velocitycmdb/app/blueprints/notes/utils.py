import re
import bleach
from bleach.css_sanitizer import CSSSanitizer

import re
import base64
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


def extract_and_save_base64_images(content, note_id):
    """
    Extract base64 images from HTML content, save as attachments,
    and replace with attachment URLs.

    Returns the modified content with attachment URLs instead of base64.
    """
    from velocitycmdb.app.blueprints.notes.models import NoteAttachment

    # Pattern to match base64 image data URLs in img tags
    # Matches: <img src="data:image/png;base64,ABC123..." ...>
    pattern = r'<img\s+([^>]*?)src=["\']data:image/([^;]+);base64,([^"\']+)["\']([^>]*)>'

    def replacer(match):
        prefix_attrs = match.group(1)  # attributes before src
        image_type = match.group(2)  # png, jpeg, gif, etc.
        base64_data = match.group(3)  # the actual base64 content
        suffix_attrs = match.group(4)  # attributes after src

        try:
            # Decode base64 to binary
            image_data = base64.b64decode(base64_data)

            # Check size limit (1MB)
            if len(image_data) > 1024 * 1024:
                # Too large - leave as is but truncate (or could reject)
                return match.group(0)

            # Determine content type and extension
            content_type = f'image/{image_type}'
            if image_type == 'jpeg':
                ext = 'jpg'
            else:
                ext = image_type

            # Generate filename
            import time
            filename = f'pasted_image_{int(time.time() * 1000)}.{ext}'

            # Save as attachment
            attachment_id = NoteAttachment.create(
                note_id=note_id,
                filename=filename,
                content_type=content_type,
                data=image_data,
                file_size=len(image_data)
            )

            # Return img tag with attachment URL
            attachment_url = f'/notes/attachments/{attachment_id}'
            return f'<img {prefix_attrs}src="{attachment_url}"{suffix_attrs}>'

        except Exception as e:
            # If anything fails, leave original intact
            print(f"Error extracting base64 image: {e}")
            return match.group(0)

    return re.sub(pattern, replacer, content, flags=re.IGNORECASE | re.DOTALL)


def get_base64_image_count(content):
    """
    Count base64 images in content (for diagnostics/warnings).
    """
    pattern = r'data:image/[^;]+;base64,'
    return len(re.findall(pattern, content))


def get_base64_total_size(content):
    """
    Estimate total size of base64 images in content.
    Returns size in bytes.
    """
    pattern = r'data:image/[^;]+;base64,([^"\']+)["\']'
    matches = re.findall(pattern, content)

    total = 0
    for b64_data in matches:
        # Base64 is ~33% overhead, so actual size is roughly 3/4 of base64 length
        total += len(b64_data) * 3 // 4

    return total


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