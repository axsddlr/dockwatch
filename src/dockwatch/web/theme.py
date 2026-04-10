"""Centralized theme configuration for the dockwatch NiceGUI dashboard."""

from __future__ import annotations

from nicegui import ui

BG_PAGE = "#141416"
BG_PANEL = "#1A1B1E"
BG_PANEL_ALT = "#18191C"
BG_TABLE_HEAD = "#114954"
BG_INPUT = "#101114"
BORDER = "rgba(255,255,255,0.08)"
BORDER_STRONG = "rgba(255,255,255,0.14)"

TEXT_PRIMARY = "#EEF2F4"
TEXT_MUTED = "#A4A9AE"
TEXT_DIM = "#6F7780"

PRIMARY = "#13C4F2"
ACCENT = "#4ADE80"
WARNING = "#F59E0B"
DANGER = "#F87171"
INFO = "#22D3EE"

STATUS_GREEN = "#3FE17F"
STATUS_RED = "#F87171"
STATUS_YELLOW = "#FBBF24"
STATUS_BLUE = "#38BDF8"

STATUS_GREEN_BG = "rgba(63,225,127,0.14)"
STATUS_RED_BG = "rgba(248,113,113,0.14)"
STATUS_YELLOW_BG = "rgba(251,191,36,0.14)"
STATUS_BLUE_BG = "rgba(56,189,248,0.14)"

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
    """Inject the Tugtainer-inspired control-panel theme into NiceGUI."""
    ui.colors(
        primary=PRIMARY,
        secondary="#0EA5C6",
        accent=ACCENT,
        dark=BG_PAGE,
        positive=STATUS_GREEN,
        negative=STATUS_RED,
        warning=STATUS_YELLOW,
        info=STATUS_BLUE,
    )

    ui.add_head_html("""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    """)

    ui.add_css(f"""
    *, *::before, *::after {{ box-sizing: border-box; }}

    html, body {{
        margin: 0;
        padding: 0;
        background: {BG_PAGE} !important;
        color: {TEXT_PRIMARY};
        font-family: 'Fira Sans', sans-serif;
        font-size: 14px;
        line-height: 1.5;
        min-height: 100vh;
        -webkit-font-smoothing: antialiased;
    }}

    body {{
        background-image:
            linear-gradient(180deg, rgba(255,255,255,0.02), transparent 180px),
            radial-gradient(circle at top right, rgba(19,196,242,0.09), transparent 34%),
            radial-gradient(circle at top left, rgba(74,222,128,0.05), transparent 30%);
    }}

    ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
    ::-webkit-scrollbar-track {{ background: {BG_PANEL_ALT}; }}
    ::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.18); border-radius: 999px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: rgba(255,255,255,0.28); }}

    .mono {{ font-family: 'Fira Code', monospace !important; }}
    .mono-sm {{ font-family: 'Fira Code', monospace !important; font-size: 12px !important; }}

    .dw-shell {{
        width: min(1260px, 100%);
        max-width: none;
        padding: 18px 18px 40px;
        gap: 14px;
        transition: margin 140ms ease;
    }}

    .dw-shell--centered {{
        margin: 0 auto;
        align-self: center;
    }}

    .dw-shell--anchored {{
        margin: 0;
        align-self: flex-start;
    }}

    .dw-nav {{
        background: rgba(18, 19, 22, 0.96) !important;
        border-bottom: 1px solid {BORDER} !important;
        min-height: 58px !important;
    }}

    .dw-drawer {{
        background: {BG_PANEL_ALT} !important;
        border-right: 1px solid {BORDER} !important;
        color: {TEXT_PRIMARY} !important;
        width: 248px !important;
    }}

    .dw-drawer-link {{
        width: 100%;
        justify-content: flex-start;
        border-radius: 8px;
        color: {TEXT_PRIMARY} !important;
        border: 1px solid transparent;
        background: transparent !important;
        min-height: 42px !important;
    }}

    .dw-drawer-link .q-btn__content {{
        justify-content: flex-start !important;
        font-weight: 600 !important;
        gap: 10px;
    }}

    .dw-drawer-link.active {{
        background: rgba(19,196,242,0.12) !important;
        border-color: rgba(19,196,242,0.2) !important;
    }}

    .dw-panel {{
        background: {BG_PANEL} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 8px !important;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.015);
    }}

    .dw-summary-strip {{
        display: grid;
        grid-template-columns: repeat(4, minmax(120px, 1fr));
        gap: 10px;
    }}

    .dw-summary-chip {{
        background: {BG_PANEL} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 8px !important;
        padding: 10px 12px;
        min-height: 66px;
    }}

    .dw-controls {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 12px 14px;
    }}

    .dw-toolbar-group {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
    }}

    .dw-btn-primary .q-btn__content {{
        font-family: 'Fira Sans', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: 0 !important;
    }}

    .dw-btn-primary {{
        background: {ACCENT} !important;
        color: #08210e !important;
        border-radius: 6px !important;
        min-height: 38px !important;
    }}

    .dw-btn-secondary {{
        background: {PRIMARY} !important;
        color: #07212a !important;
        border-radius: 6px !important;
        min-height: 34px !important;
    }}

    .dw-btn-ghost {{
        background: #111215 !important;
        color: {TEXT_PRIMARY} !important;
        border: 1px solid {BORDER_STRONG} !important;
        border-radius: 6px !important;
        min-height: 34px !important;
    }}

    .dw-btn-ghost .q-btn__content {{
        font-size: 12px !important;
        font-weight: 600 !important;
    }}

    .dw-input-shell {{
        background: {BG_INPUT};
        border: 1px solid {BORDER_STRONG};
        border-radius: 6px;
    }}

    .dw-table-wrap {{
        background: {BG_PANEL} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 8px !important;
        overflow: hidden;
    }}

    .dw-table-head {{
        display: grid;
        grid-template-columns: minmax(250px, 2.4fr) minmax(100px, .9fr) minmax(110px, .8fr) minmax(180px, 1.25fr) minmax(180px, 1.35fr) minmax(170px, 1fr);
        gap: 12px;
        align-items: center;
        padding: 11px 16px;
        background: {BG_TABLE_HEAD};
        border-bottom: 1px solid rgba(255,255,255,0.08);
    }}

    .dw-table-row {{
        display: grid;
        grid-template-columns: minmax(250px, 2.4fr) minmax(100px, .9fr) minmax(110px, .8fr) minmax(180px, 1.25fr) minmax(180px, 1.35fr) minmax(170px, 1fr);
        gap: 12px;
        align-items: center;
        padding: 12px 16px;
        background: {BG_PANEL};
        border-bottom: 1px solid rgba(255,255,255,0.05);
    }}

    .dw-table-row:last-child {{ border-bottom: 0; }}

    .dw-col-label {{
        font-family: 'Fira Code', monospace;
        font-size: 12px;
        font-weight: 600;
        color: rgba(255,255,255,0.92);
        text-transform: none;
    }}

    .dw-name-cell {{
        display: flex;
        align-items: center;
        gap: 10px;
        min-width: 0;
    }}

    .dw-name-stack {{
        display: flex;
        flex-direction: column;
        min-width: 0;
        gap: 3px;
    }}

    .dw-name-title {{
        color: {TEXT_PRIMARY};
        font-size: 15px;
        font-weight: 600;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}

    .dw-name-subtitle {{
        color: {TEXT_MUTED};
        font-family: 'Fira Code', monospace;
        font-size: 11px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}

    .dw-data-cell {{
        color: {TEXT_PRIMARY};
        font-size: 12px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}

    .dw-data-cell.mono {{
        font-size: 11px;
    }}

    .status-pill {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 28px;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.02em;
        text-transform: none;
        font-family: 'Fira Sans', sans-serif;
        border: 1px solid rgba(255,255,255,0.05);
    }}

    .status-dot {{
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 999px;
        flex-shrink: 0;
        box-shadow: 0 0 0 2px rgba(255,255,255,0.04);
    }}
    .dot-green  {{ background: {STATUS_GREEN}; }}
    .dot-red    {{ background: {STATUS_RED}; }}
    .dot-yellow {{ background: {STATUS_YELLOW}; }}
    .dot-blue   {{ background: {STATUS_BLUE}; }}

    .section-label {{
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: {TEXT_MUTED};
        font-family: 'Fira Code', monospace;
    }}

    .dw-expansion {{
        background: {BG_PANEL} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 8px !important;
    }}

    .dw-expansion .q-expansion-item__header,
    .q-field__native,
    .q-field__input {{
        color: {TEXT_PRIMARY} !important;
    }}

    .q-field--dark .q-field__label {{ color: {TEXT_MUTED} !important; }}

    .dw-footer {{
        border-top: 1px solid {BORDER};
        color: {TEXT_DIM};
        font-size: 12px;
    }}

    *:focus-visible {{
        outline: 2px solid {PRIMARY};
        outline-offset: 2px;
        border-radius: 4px;
    }}

    @media (max-width: 980px) {{
        .dw-drawer {{
            width: 248px !important;
        }}

        .dw-summary-strip {{
            grid-template-columns: repeat(2, minmax(120px, 1fr));
        }}

        .dw-table-head {{
            display: none;
        }}

        .dw-table-row {{
            grid-template-columns: 1fr;
            gap: 8px;
        }}

        .dw-data-cell::before {{
            content: attr(data-label);
            display: block;
            color: {TEXT_MUTED};
            font-family: 'Fira Code', monospace;
            font-size: 10px;
            letter-spacing: 0.06em;
            margin-bottom: 2px;
            text-transform: uppercase;
        }}
    }}

    @media (max-width: 640px) {{
        .dw-summary-strip {{
            grid-template-columns: 1fr 1fr;
        }}

        .dw-shell {{
            padding: 12px 10px 28px;
        }}
    }}

    @media (prefers-reduced-motion: reduce) {{
        * {{ transition: none !important; }}
    }}
    """)
