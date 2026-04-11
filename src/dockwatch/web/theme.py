"""Centralized theme configuration for the dockwatch NiceGUI dashboard."""

from __future__ import annotations

from nicegui import ui

BG_PAGE = "#141416"
BG_PANEL = "#1B1C1F"
BG_PANEL_ALT = "#17181B"
BG_TABLE_HEAD = "#134A54"
BG_INPUT = "#101114"
BORDER = "rgba(255,255,255,0.07)"
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
        width: min(1240px, 100%);
        max-width: none;
        padding: 20px 20px 40px;
        gap: 12px;
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
        background: rgba(20, 21, 24, 0.98) !important;
        border-bottom: 1px solid {BORDER} !important;
        min-height: 46px !important;
    }}

    .dw-drawer {{
        background: {BG_PANEL_ALT} !important;
        border-right: 1px solid {BORDER} !important;
        color: {TEXT_PRIMARY} !important;
        width: 246px !important;
    }}

    .dw-drawer-link {{
        width: 100%;
        justify-content: flex-start;
        border-radius: 6px;
        color: {TEXT_PRIMARY} !important;
        border: 1px solid transparent;
        background: transparent !important;
        min-height: 36px !important;
    }}

    .dw-drawer-link .q-btn__content {{
        justify-content: flex-start !important;
        font-weight: 600 !important;
        gap: 10px;
    }}

    .dw-drawer-link.active {{
        background: rgba(19,196,242,0.14) !important;
        border-color: rgba(19,196,242,0.18) !important;
    }}

    .dw-top-brand {{
        font-size: 17px;
        font-weight: 700;
        color: {TEXT_PRIMARY};
        letter-spacing: -0.03em;
    }}

    .dw-version-badge {{
        padding: 3px 8px;
        background: #F5F7F8;
        color: #111315;
        border-radius: 6px;
        font-family: 'Fira Code', monospace;
        font-size: 11px;
        font-weight: 600;
        line-height: 1;
    }}

    .dw-panel {{
        background: {BG_PANEL} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 7px !important;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.02);
    }}

    .dw-summary-strip {{
        display: grid;
        grid-template-columns: repeat(4, minmax(120px, 1fr));
        gap: 8px;
    }}

    .dw-summary-chip {{
        background: {BG_PANEL} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 7px !important;
        padding: 10px 12px 9px;
        min-height: 60px;
    }}

    .dw-summary-chip .section-label {{
        margin-bottom: 6px;
    }}

    .dw-page-meta {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 2px 2px 4px;
    }}

    .dw-controls {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: flex-start;
        gap: 12px;
        padding: 14px 14px 10px;
    }}

    .dw-toolbar-group {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 9px;
    }}

    .dw-toolbar-meta {{
        margin-left: auto;
    }}

    .dw-filter-row {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        padding: 0 14px 12px;
        border-top: 1px solid {BORDER};
    }}

    .dw-btn-primary .q-btn__content {{
        font-family: 'Fira Sans', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: 0.01em !important;
        font-size: 12px !important;
    }}

    .dw-btn-primary {{
        background: {PRIMARY} !important;
        color: #04161d !important;
        border-radius: 6px !important;
        min-height: 34px !important;
    }}

    .dw-btn-secondary {{
        background: {PRIMARY} !important;
        color: #051820 !important;
        border-radius: 6px !important;
        min-height: 30px !important;
        padding: 0 10px !important;
    }}

    .dw-btn-ghost {{
        background: #101114 !important;
        color: {TEXT_PRIMARY} !important;
        border: 1px solid {BORDER_STRONG} !important;
        border-radius: 6px !important;
        min-height: 30px !important;
        padding: 0 10px !important;
    }}

    .dw-btn-ghost .q-btn__content {{
        font-size: 11px !important;
        font-weight: 600 !important;
    }}

    .dw-input-shell {{
        background: {BG_INPUT};
        border: 1px solid {BORDER_STRONG};
        border-radius: 6px;
    }}

    .dw-section-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 0 6px 10px;
        border-bottom: 1px solid {BORDER};
    }}

    .dw-table-wrap {{
        background: {BG_PANEL} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 7px !important;
        overflow: hidden;
    }}

    .dw-table-head {{
        display: grid;
        grid-template-columns: minmax(250px, 2.4fr) minmax(100px, .9fr) minmax(110px, .8fr) minmax(180px, 1.25fr) minmax(180px, 1.35fr) minmax(170px, 1fr);
        gap: 12px;
        align-items: center;
        padding: 10px 16px;
        background: {BG_TABLE_HEAD};
        border-bottom: 1px solid rgba(255,255,255,0.08);
    }}

    .dw-table-row {{
        display: grid;
        grid-template-columns: minmax(250px, 2.4fr) minmax(100px, .9fr) minmax(110px, .8fr) minmax(180px, 1.25fr) minmax(180px, 1.35fr) minmax(170px, 1fr);
        gap: 12px;
        align-items: center;
        padding: 10px 16px;
        background: {BG_PANEL};
        border-bottom: 1px solid rgba(255,255,255,0.05);
    }}

    .dw-table-row:last-child {{ border-bottom: 0; }}

    .dw-col-label {{
        font-family: 'Fira Code', monospace;
        font-size: 11px;
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
        font-size: 14px;
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

    .dw-source-pill {{
        display: inline-flex;
        align-items: center;
        width: fit-content;
        min-height: 18px;
        padding: 1px 6px;
        border-radius: 999px;
        background: rgba(255,255,255,0.06);
        color: {TEXT_PRIMARY};
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }}

    .dw-registry-link {{
        display: inline-flex;
        align-items: center;
        min-height: 22px;
        padding: 2px 8px;
        border-radius: 999px;
        background: rgba(19,196,242,0.14);
        border: 1px solid rgba(19,196,242,0.24);
        color: {PRIMARY} !important;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-decoration: none !important;
        text-transform: uppercase;
    }}

    .dw-registry-link:hover {{
        background: rgba(19,196,242,0.22);
        border-color: rgba(19,196,242,0.34);
    }}

    .dw-registry-link-icon {{
        color: {PRIMARY};
        opacity: 0.95;
    }}

    .dw-data-cell {{
        color: {TEXT_PRIMARY};
        font-size: 11px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}

    .dw-data-cell.mono {{
        font-size: 11px;
    }}

    .dw-actions {{
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 8px;
    }}

    .status-pill {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 24px;
        padding: 3px 9px;
        border-radius: 6px;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.02em;
        text-transform: none;
        font-family: 'Fira Sans', sans-serif;
        border: 1px solid rgba(255,255,255,0.05);
    }}

    .dw-bump-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 20px;
        padding: 2px 7px;
        border-radius: 999px;
        border: 1px solid transparent;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.04em;
        white-space: nowrap;
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

    .dw-settings-wrap {{
        width: min(920px, 100%);
        gap: 12px;
    }}

    .dw-settings-grid {{
        display: grid;
        grid-template-columns: minmax(180px, 220px) minmax(0, 1fr);
        gap: 14px;
        align-items: start;
    }}

    .dw-settings-side {{
        display: flex;
        flex-direction: column;
        gap: 8px;
    }}

    .dw-settings-main {{
        display: flex;
        flex-direction: column;
        gap: 12px;
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

        .dw-toolbar-meta {{
            margin-left: 0;
        }}

        .dw-settings-grid {{
            grid-template-columns: 1fr;
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
