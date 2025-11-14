
# Network Management - Material Design 3 Style Guide

## Overview

This style guide defines the design system for the Network Management application, built on Material Design 3 principles with a focus on flat, clean aesthetics and functional clarity.

## Design Principles

### 1. Flat Design
- **Minimal shadows** - Use only when necessary for hierarchy
- **Clean borders** - 1px solid lines with consistent colors
- **Simple shapes** - Rounded corners using shape tokens (2px-6px range)
- **No gradients** - Solid colors only

### 2. Functional First
- **Information hierarchy** - Clear visual hierarchy without decorative elements
- **Accessibility** - High contrast, readable text, semantic markup
- **Performance** - Lightweight styles, efficient transitions

### 3. Consistency
- **Design tokens** - Use CSS custom properties for all values
- **Component patterns** - Reusable, documented components
- **Predictable behavior** - Consistent interactions across the application

## File Structure

```
app/
├── static/
│   ├── css/
│   │   └── themes.css          # All theme definitions and components
│   └── js/
│       └── theme-toggle.js     # Theme switching functionality
├── templates/
│   ├── base.html              # Base template with theme system
│   ├── assets/
│   │   ├── devices.html       # Device listing page
│   │   └── device_detail.html # Individual device view
│   ├── capture/
│   │   └── search.html        # Capture search interface
│   ├── dashboard/
│   │   └── index.html         # Main dashboard
│   └── auth/
│       └── login.html         # Authentication
└── blueprints/                # Flask route handlers
    ├── assets/
    ├── capture/
    ├── dashboard/
    └── auth/
```

## Theme System

### Current Implementation

The entire design system is contained in a single file: `app/static/css/themes.css`

This file includes:
- CSS custom properties for all three themes
- All component definitions
- Responsive utilities
- Scrollbar theming
- Animation keyframes

### Theme Switching

Themes are controlled via `data-theme` attribute:

```html
<html data-theme="light">   <!-- Default burgundy/cream theme -->
<html data-theme="dark">    <!-- Dark gray with burgundy accents -->
<html data-theme="cyber">   <!-- Matrix-style with teal primary -->
```

Theme switching is handled by `theme-toggle.js` which:
- Provides dropdown interface in navigation
- Persists theme choice in localStorage
- Applies theme immediately on change

### Theme Colors

#### Light Theme (Default)
- **Primary**: `#752d46` (burgundy)
- **Background**: `#fefcf8` (cream)
- **Surface**: `#ffffff` (white)
- **Accent surfaces**: Warm beiges (`#f7f1e8`, `#f0e6d6`)

#### Dark Theme
- **Primary**: `#752d46` (same burgundy for consistency)
- **Background**: `#0f0f0f` (deep black)
- **Surface**: `#1a1a1a` (dark gray)
- **Surface containers**: Cool grays (`#2a2a2a`, `#333333`)

#### Cyber Theme
- **Primary**: `#00ccff` (bright teal)
- **Secondary**: `#00ff41` (matrix green)
- **Background**: `#000510` (dark blue-black)
- **Special effects**: Glow shadows using teal/green

## Component Architecture

### Layered CSS Structure

The themes.css file uses CSS `@layer` for organization:

```css
@layer tokens { /* CSS custom properties */ }
@layer reset { /* Minimal reset */ }
@layer base { /* Base styles */ }
@layer typography { /* Typography classes */ }
@layer components { /* All UI components */ }
@layer utilities { /* Helper classes */ }
```

### Component Prefix System

All components use `md-` prefix for consistency:

- `md-card` - Card containers
- `md-button` - Button variants  
- `md-nav` - Navigation components
- `md-textfield` - Form inputs
- `md-badge` - Status indicators
- `md-table` - Data tables

## Current Components

### Cards
```css
.md-card {
    background: var(--md-surface);
    border: 1px solid var(--md-outline-variant);
    border-radius: var(--md-shape-corner-small); /* 2px */
}

.md-card-header {
    padding: 20px 28px 16px; /* Updated for better spacing */
    border-bottom: 1px solid var(--md-outline-variant);
    background: var(--md-surface-container);
}

.md-card-content {
    padding: 28px; /* Increased from 24px */
}
```

### Buttons
```css
.md-button {
    padding: 10px 24px; /* Updated - increased right padding */
    border-radius: var(--md-shape-corner-small);
    font: var(--md-typescale-label-large);
    transition: background-color var(--md-motion-duration-short4) var(--md-motion-easing-standard);
}

.md-button-filled {
    background: var(--md-primary);
    color: var(--md-on-primary);
}

.md-button-outlined {
    border: 1px solid var(--md-outline);
    color: var(--md-primary);
}

.md-button-text {
    padding: 10px 20px; /* Increased for better spacing */
    background: transparent;
}
```

### Navigation
```css
.md-nav-link {
    padding: 10px 20px; /* Updated spacing */
    border-radius: var(--md-shape-corner-small);
    display: flex;
    align-items: center;
    gap: 12px;
}

.md-nav-link.active {
    background: var(--md-secondary-container);
    color: var(--md-on-secondary-container);
}
```

### Forms
```css
.md-form-field input,
.md-form-field select {
    padding: 12px 18px; /* Increased right padding */
    border: 1px solid var(--md-outline);
    border-radius: var(--md-shape-corner-small);
    transition: border-color var(--md-motion-duration-short4) var(--md-motion-easing-standard);
}

.md-form-field input:focus {
    border-color: var(--md-primary);
    border-width: 2px;
    padding: 11px 17px; /* Compensate for border increase */
}
```

## Scrollbar Theming

Custom scrollbars for all themes:

```css
/* Light/Dark themes - subtle styling */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

/* Cyber theme - glowing effects */
[data-theme="cyber"] ::-webkit-scrollbar-thumb {
    background: var(--md-primary);
    box-shadow: 0 0 4px rgba(0, 204, 255, 0.4);
}
```

## Page Templates

### Base Template Structure
```html
<!-- base.html -->
<html data-theme="light">
<head>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/themes.css') }}">
</head>
<body>
    <nav class="md-nav">
        <!-- Theme selector -->
        <select id="theme-selector">
            <option value="light">Light</option>
            <option value="dark">Dark</option>
            <option value="cyber">Cyber</option>
        </select>
    </nav>
    
    <main>
        {% block content %}{% endblock %}
    </main>
    
    <script src="{{ url_for('static', filename='js/theme-toggle.js') }}"></script>
</body>
</html>
```

### Current Pages

#### Dashboard (`templates/dashboard/index.html`)
- Device overview cards
- Status indicators
- Quick action buttons

#### Device Management (`templates/assets/devices.html`)
- Device listing table
- Status badges
- Filter controls

#### Device Detail (`templates/assets/device_detail.html`)
- Device information cards
- Status indicators
- Action buttons (SSH, Capture, Export)

#### Capture Search (`templates/capture/search.html`)
- Complex search form with embedded styles
- Results display with syntax highlighting
- Modal viewer for capture content

## Recent Updates

### Spacing Improvements
- Increased button padding to prevent text crowding
- Enhanced form field spacing
- Better card header/content padding
- Improved navigation link spacing

### Theme Consistency
- Cyber theme uses teal primary instead of green
- Dark theme uses burgundy primary on gray surfaces  
- All themes share consistent spacing and typography

### Component Additions
- Enhanced scrollbar theming for all themes
- Improved modal components
- Better badge variants
- Enhanced state indicators

## Development Guidelines

### Adding New Components

1. **Define in themes.css** using CSS custom properties
2. **Test in all three themes** (light, dark, cyber)
3. **Follow flat design principles** - no gradients or heavy shadows
4. **Use consistent spacing** from the defined spacing system
5. **Update this style guide** with new component documentation

### Theme Testing

```javascript
// Test component in all themes
const themes = ['light', 'dark', 'cyber'];
themes.forEach(theme => {
    document.documentElement.setAttribute('data-theme', theme);
    // Verify component appearance
});
```

### Best Practices

**Do:**
- Use CSS custom properties for all values
- Test across all three themes
- Follow the established spacing system
- Use semantic HTML elements
- Include proper focus states

**Don't:**
- Hardcode colors or spacing values
- Use gradients or heavy shadows
- Mix different icon libraries
- Create components without theme support
- Ignore mobile responsiveness

---
