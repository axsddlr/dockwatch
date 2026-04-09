"""Centralized theme configuration for the dockwatch NiceGUI dashboard."""

from __future__ import annotations

from nicegui import ui

# ── Color palette ──────────────────────────────────────────────────────────────
BG_DEEP = "#0A0E1A"
BG_SURFACE = "#111827"
BG_CARD = "#1C2333"
BORDER = "rgba(255,255,255,0.08)"
BORDER_HOVER = "rgba(255,255,255,0.16)"

TEXT_PRIMARY = "#F1F5F9"
TEXT_MUTED = "#94A3B8"
TEXT_DIM = "#4B5563"

PRIMARY = "#2563EB"
ACCENT = "#F97316"

STATUS_GREEN = "#22C55E"
STATUS_RED = "#EF4444"
STATUS_YELLOW = "#EAB308"
STATUS_BLUE = "#3B82F6"

STATUS_GREEN_BG = "rgba(34,197,94,0.12)"
STATUS_RED_BG = "rgba(239,68,68,0.12)"
STATUS_YELLOW_BG = "rgba(234,179,8,0.12)"
STATUS_BLUE_BG = "rgba(59,130,246,0.12)"

# ── Status maps ────────────────────────────────────────────────────────────────
STATUS_COLOR: dict[str, str] = {
    "UP-TO-DATE": STATUS_GREEN,
    "OUTDATED": STATUS_RED,
    "UNKNOWN": STATUS_YELLOW,
    "PINNED": STATUS_BLUE,
}

STATUS_BG: dict[str, str] = {
    "UP-TO-DATE": STATUS_GREEN_BG,
    "OUTDATED": STATUS_RED_BG,
    "UNKNOWN": STATUS_YELLOW_BG,
    "PINNED": STATUS_BLUE_BG,
}


def apply_theme() -> None:
    """Inject dark theme, fonts, and global CSS into the NiceGUI app.

    Must be called before ui.run(). Do not call ui.dark_mode() here —
    dark mode is enabled via dark=True in ui.run() to avoid global scope conflicts.
    """
    ui.colors(
        primary=PRIMARY,
        secondary="#1D4ED8",
        accent=ACCENT,
        dark=BG_DEEP,
        positive=STATUS_GREEN,
        negative=STATUS_RED,
        warning=STATUS_YELLOW,
        info=STATUS_BLUE,
    )

    # Google Fonts: Fira Code + Fira Sans
    ui.add_head_html("""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    """)

    ui.add_css(f"""
    /* ── Reset & base ─────────────────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; }}

    html, body {{
        margin: 0;
        padding: 0;
        background: {BG_DEEP} !important;
        color: {TEXT_PRIMARY};
        font-family: 'Fira Sans', sans-serif;
        font-size: 14px;
        line-height: 1.6;
        min-height: 100vh;
        -webkit-font-smoothing: antialiased;
    }}

    /* ── Scrollbar ───────────────────────────────────────────────────────── */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: {BG_SURFACE}; }}
    ::-webkit-scrollbar-thumb {{ background: #374151; border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: #4B5563; }}

    /* ── Monospace utility ───────────────────────────────────────────────── */
    .mono {{ font-family: 'Fira Code', monospace !important; }}
    .mono-sm {{ font-family: 'Fira Code', monospace !important; font-size: 12px !important; }}

    /* ── Container cards ─────────────────────────────────────────────────── */
    .dw-card {{
        background: {BG_CARD} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 10px !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
        overflow: hidden;
    }}
    .dw-card:hover {{
        border-color: {BORDER_HOVER} !important;
        box-shadow: 0 0 0 1px rgba(37,99,235,0.2), 0 4px 20px rgba(0,0,0,0.4) !important;
    }}

    /* ── Stat cards ───────────────────────────────────────────────────────── */
    .dw-stat-card {{
        background: {BG_CARD} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 10px !important;
        transition: border-color 0.2s ease;
    }}

    /* ── Status pills ─────────────────────────────────────────────────────── */
    .status-pill {{
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 3px 10px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        font-family: 'Fira Code', monospace;
        white-space: nowrap;
    }}

    /* ── Pulsing status dot ───────────────────────────────────────────────── */
    @keyframes pulse-ring {{
        0%   {{ transform: scale(0.8); opacity: 1; }}
        70%  {{ transform: scale(1.4); opacity: 0; }}
        100% {{ transform: scale(1.4); opacity: 0; }}
    }}

    .status-dot {{
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        position: relative;
        flex-shrink: 0;
    }}
    .status-dot::after {{
        content: '';
        position: absolute;
        inset: -3px;
        border-radius: 50%;
        border: 2px solid currentColor;
        animation: pulse-ring 2s ease-out infinite;
    }}
    .dot-green  {{ color: {STATUS_GREEN};  background: {STATUS_GREEN}; }}
    .dot-red    {{ color: {STATUS_RED};    background: {STATUS_RED}; }}
    .dot-yellow {{ color: {STATUS_YELLOW}; background: {STATUS_YELLOW}; }}
    .dot-blue   {{ color: {STATUS_BLUE};   background: {STATUS_BLUE}; }}

    /* Suppress pulse for stable states */
    .dot-green::after, .dot-blue::after {{ animation: none; }}

    /* ── Nav header ───────────────────────────────────────────────────────── */
    .dw-nav {{
        background: rgba(10,14,26,0.85) !important;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-bottom: 1px solid {BORDER} !important;
        position: sticky;
        top: 0;
        z-index: 100;
    }}

    /* ── Section labels ───────────────────────────────────────────────────── */
    .section-label {{
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: {TEXT_MUTED};
        font-family: 'Fira Code', monospace;
    }}

    /* ── Ghost action buttons ─────────────────────────────────────────────── */
    .dw-btn-ghost .q-btn__content {{ color: {TEXT_MUTED} !important; }}
    .dw-btn-ghost:hover .q-btn__content {{ color: {TEXT_PRIMARY} !important; }}

    /* ── Left accent border by status ────────────────────────────────────── */
    .border-l-green  {{ border-left: 3px solid {STATUS_GREEN} !important; }}
    .border-l-red    {{ border-left: 3px solid {STATUS_RED} !important; }}
    .border-l-yellow {{ border-left: 3px solid {STATUS_YELLOW} !important; }}
    .border-l-blue   {{ border-left: 3px solid {STATUS_BLUE} !important; }}

    /* ── Input fields ─────────────────────────────────────────────────────── */
    .q-field__native, .q-field__input {{
        color: {TEXT_PRIMARY} !important;
        font-family: 'Fira Sans', sans-serif !important;
    }}
    .q-field--dark .q-field__label {{ color: {TEXT_MUTED} !important; }}

    /* ── Expansion panel ─────────────────────────────────────────────────── */
    .dw-expansion {{
        background: {BG_CARD} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 10px !important;
    }}
    .dw-expansion .q-expansion-item__header {{
        color: {TEXT_PRIMARY} !important;
    }}

    /* ── Footer ───────────────────────────────────────────────────────────── */
    .dw-footer {{
        border-top: 1px solid {BORDER};
        color: {TEXT_DIM};
        font-size: 12px;
    }}

    /* ── Focus states ─────────────────────────────────────────────────────── */
    *:focus-visible {{
        outline: 2px solid {PRIMARY};
        outline-offset: 2px;
        border-radius: 4px;
    }}

    /* ── Reduced motion ───────────────────────────────────────────────────── */
    @media (prefers-reduced-motion: reduce) {{
        .status-dot::after {{ animation: none; }}
        * {{ transition: none !important; }}
    }}
    """)
