"""PDF report generation for Battery Sizer.

Creates a clean 3-page A4 report:
1. executive summary
2. charts
3. detailed analysis
"""

from __future__ import annotations

from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from fpdf import FPDF


SOLEOL_ORANGE = (233, 78, 53)
DARK = (0, 0, 0)
TEXT = (35, 35, 35)
MUTED = (100, 110, 120)
BLUE = (37, 99, 235)
GREEN = (34, 160, 85)
ORANGE = (245, 130, 32)
PURPLE = (126, 58, 242)
LIGHT_BG = (248, 250, 252)
LIGHT_ORANGE = (255, 244, 239)
LIGHT_GREEN = (236, 253, 245)
BORDER = (220, 225, 230)

CARD_TITLE_SIZE = 7
CARD_VALUE_SIZE = 14
CARD_SUB_SIZE = 7
SIDEBAR_LABEL_SIZE = 7.5
SIDEBAR_VALUE_SIZE = 8.2
FOOTER_SIZE = 7


def _tx(s) -> str:
    repl = {
        "—": "-",
        "–": "-",
        "→": "->",
        "≥": ">=",
        "≤": "<=",
        "≈": "~",
        "•": "-",
        "✅": "",
        "⚠️": "!",
        "’": "'",
        "œ": "oe",
        "…": "...",
        "é": "é",
        "è": "è",
        "ê": "ê",
        "à": "à",
        "ç": "ç",
        "É": "É",
        "À": "À",
        "Ç": "Ç",
    }
    s = str(s)
    for k, v in repl.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _kwh(v) -> str:
    return f"{float(v):,.0f}".replace(",", " ")


def _chf(v) -> str:
    return f"{float(v):,.0f}".replace(",", " ")


def _safe_pct(num, den) -> float:
    return float(num) / float(den) * 100 if float(den) > 0 else 0.0


def _pdf_bytes(pdf: FPDF) -> bytes:
    out = pdf.output()
    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin-1")


class ReportPDF(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-10)
        self.set_font("Arial", "", FOOTER_SIZE)
        self.set_text_color(*MUTED)
        self.cell(0, 5, _tx("SOLEOL - Battery Sizer"), align="L")
        self.set_y(-10)
        self.cell(0, 5, _tx(f"Page {self.page_no()} / {{nb}}"), align="R")


def _add_section_title(pdf: FPDF, title: str, x: float, y: float, w: float):
    pdf.set_xy(x, y)
    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.cell(w, 8, _tx(title), ln=False)


def _metric_box(
    pdf: FPDF,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    value: str,
    sub: str = "",
    color=BLUE,
    label_size: float = CARD_TITLE_SIZE,
    value_size: float = CARD_VALUE_SIZE,
    sub_size: float = CARD_SUB_SIZE,
):
    pdf.set_draw_color(*BORDER)
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(x, y, w, h, style="DF")

    pdf.set_xy(x + 4, y + 4)
    pdf.set_font("Arial", "B", label_size)
    pdf.set_text_color(*TEXT)
    pdf.multi_cell(w - 8, 4, _tx(label.upper()), align="L")

    pdf.set_xy(x + 4, y + 13)
    pdf.set_font("Arial", "B", value_size)
    pdf.set_text_color(*color)
    pdf.cell(w - 8, 8, _tx(value), ln=True)

    if sub:
        pdf.set_xy(x + 4, y + h - 9)
        pdf.set_font("Arial", "", sub_size)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(w - 8, 4, _tx(sub), align="L")



def _flow_metric_box(
    pdf: FPDF,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    value: str,
    sub: str = "",
    color=BLUE,
):
    pdf.set_draw_color(*BORDER)
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(x, y, w, h, style="DF")

    # Titre centré
    pdf.set_xy(x + 3, y + 4)
    pdf.set_font("Arial", "B", 7.2)
    pdf.set_text_color(*TEXT)
    pdf.cell(w - 6, 4, _tx(label.upper()), align="C")

    # Valeur colorée plus petite et parfaitement centrée
    pdf.set_xy(x + 3, y + 10.5)
    pdf.set_font("Arial", "B", 12.5)
    pdf.set_text_color(*color)
    pdf.cell(w - 6, 8, _tx(value), align="C")

    # Sous-titre centré
    if sub:
        pdf.set_xy(x + 3, y + h - 8)
        pdf.set_font("Arial", "", 7)
        pdf.set_text_color(*MUTED)
        pdf.cell(w - 6, 4, _tx(sub), align="C")

def _info_box(pdf: FPDF, x: float, y: float, w: float, h: float, title: str, text: str, fill=LIGHT_ORANGE, border=SOLEOL_ORANGE):
    pdf.set_draw_color(*border)
    pdf.set_fill_color(*fill)
    pdf.rect(x, y, w, h, style="DF")
    pdf.set_xy(x + 5, y + 4)
    pdf.set_font("Arial", "B", 8)
    pdf.set_text_color(*border)
    pdf.cell(w - 10, 5, _tx(title), ln=True)
    pdf.set_xy(x + 5, y + 11)
    pdf.set_font("Arial", "", 9)
    pdf.set_text_color(*TEXT)
    pdf.multi_cell(w - 10, 4, _tx(text))


def _draw_arrow(pdf: FPDF, x1: float, y: float, x2: float, color, dashed: bool = False):
    """Simple horizontal arrow."""
    pdf.set_draw_color(*color)
    if dashed:
        step = 3.0
        x = x1
        while x < x2 - 2:
            pdf.line(x, y, min(x + 1.8, x2 - 2), y)
            x += step
    else:
        pdf.line(x1, y, x2 - 2, y)

    pdf.line(x2 - 5, y - 2, x2 - 2, y)
    pdf.line(x2 - 5, y + 2, x2 - 2, y)


def _draw_sun(pdf: FPDF, cx: float, cy: float, r: float = 3.0):
    pdf.set_draw_color(*ORANGE)
    pdf.ellipse(cx - r, cy - r, 2 * r, 2 * r)
    rays = [
        (0, -1), (0.7, -0.7), (1, 0), (0.7, 0.7),
        (0, 1), (-0.7, 0.7), (-1, 0), (-0.7, -0.7),
    ]
    for dx, dy in rays:
        pdf.line(
            cx + dx * (r + 1.2), cy + dy * (r + 1.2),
            cx + dx * (r + 3.2), cy + dy * (r + 3.2),
        )


def _draw_panel(pdf: FPDF, x: float, y: float, w: float = 13, h: float = 8):
    pdf.set_draw_color(*ORANGE)
    pdf.rect(x, y, w, h)
    pdf.line(x + w / 3, y, x + w / 3, y + h)
    pdf.line(x + 2 * w / 3, y, x + 2 * w / 3, y + h)
    pdf.line(x, y + h / 2, x + w, y + h / 2)
    pdf.line(x + w / 2, y + h, x + w / 2, y + h + 3)
    pdf.line(x + w / 2 - 3, y + h + 3, x + w / 2 + 3, y + h + 3)


def _draw_house(pdf: FPDF, x: float, y: float, w: float = 13, h: float = 11):
    pdf.set_draw_color(*TEXT)
    roof_y = y + 4
    pdf.line(x, roof_y, x + w / 2, y)
    pdf.line(x + w / 2, y, x + w, roof_y)
    pdf.rect(x + 1.5, roof_y, w - 3, h - 4)
    pdf.rect(x + 4.8, y + 7.2, 3.2, 3.8)
    pdf.rect(x + 8.9, y + 6.2, 2.1, 2.1)


def _draw_battery(pdf: FPDF, x: float, y: float, w: float = 8, h: float = 14):
    pdf.set_draw_color(*GREEN)
    pdf.rect(x, y + 1.5, w, h - 1.5)
    pdf.rect(x + 2.3, y, w - 4.6, 1.5)
    for i in range(3):
        yy = y + 4 + i * 3
        pdf.set_fill_color(*GREEN)
        pdf.rect(x + 1.5, yy, w - 3, 1.8, style="F")


def _draw_grid(pdf: FPDF, x: float, y: float, w: float = 11, h: float = 16):
    pdf.set_draw_color(76, 60, 170)
    cx = x + w / 2
    pdf.line(cx, y, x + 1, y + h)
    pdf.line(cx, y, x + w - 1, y + h)
    pdf.line(x + 1, y + h, x + w - 1, y + h)
    pdf.line(x + 2, y + 5, x + w - 2, y + 5)
    pdf.line(x + 0.5, y + 9, x + w - 0.5, y + 9)
    pdf.line(x + 2.2, y + 13, x + w - 2.2, y + 13)
    pdf.line(x + 2, y + 5, x + w - 2, y + 9)
    pdf.line(x + w - 2, y + 5, x + 2, y + 9)
    pdf.line(x + 0.5, y + 9, x + w - 2.2, y + 13)
    pdf.line(x + w - 0.5, y + 9, x + 2.2, y + 13)


def _battery_flow_diagram(pdf: FPDF, x: float, y: float, w: float, h: float):
    """Vector diagram for the free space on page 1."""
    pdf.set_draw_color(*BORDER)
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(x, y, w, h, style="DF")

    pdf.set_xy(x + 5, y + 4)
    pdf.set_font("Arial", "B", 9)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.cell(w - 10, 5, _tx("FONCTIONNEMENT AVEC BATTERIE"))

    pdf.set_xy(x + 5, y + 10)
    pdf.set_font("Arial", "", 6.6)
    pdf.set_text_color(*MUTED)
    pdf.cell(
        w - 10,
        4,
        _tx("Le surplus solaire est stocké pour être utilisé lorsque la production ne suffit plus."),
    )

    # 5 étapes régulièrement espacées
    centers = [x + 13, x + 42, x + 71, x + 100, x + 129]
    icon_y = y + 24

    _draw_sun(pdf, centers[0], icon_y - 4, 2.3)
    _draw_panel(pdf, centers[0] - 6.5, icon_y, 13, 7.5)

    _draw_house(pdf, centers[1] - 6.5, icon_y - 1, 13, 11)

    _draw_battery(pdf, centers[2] - 4, icon_y - 2, 8, 14)

    _draw_house(pdf, centers[3] - 6.5, icon_y - 1, 13, 11)
    # Petit croissant / indication soirée
    pdf.set_draw_color(*GREEN)
    pdf.ellipse(centers[3] + 5.2, icon_y - 4.5, 3.5, 3.5)
    pdf.set_fill_color(255, 255, 255)
    pdf.ellipse(centers[3] + 6.0, icon_y - 5.0, 3.5, 3.5, style="F")

    _draw_grid(pdf, centers[4] - 5.5, icon_y - 3.5, 11, 15)

    # Flèches entre étapes
    arrow_y = icon_y + 4
    _draw_arrow(pdf, centers[0] + 8, arrow_y, centers[1] - 8, ORANGE)
    _draw_arrow(pdf, centers[1] + 8, arrow_y, centers[2] - 7, GREEN)
    _draw_arrow(pdf, centers[2] + 7, arrow_y, centers[3] - 8, GREEN, dashed=True)
    _draw_arrow(pdf, centers[3] + 8, arrow_y, centers[4] - 7, (76, 60, 170), dashed=True)

    # Titres des étapes
    labels = [
        ("1. Production solaire", ORANGE),
        ("2. Priorité maison", ORANGE),
        ("3. Charge batterie", GREEN),
        ("4. Restitution", GREEN),
        ("5. Réseau", (76, 60, 170)),
    ]
    descriptions = [
        "Production en journée",
        "Le solaire alimente le site",
        "Le surplus est stocké",
        "La batterie prend le relais",
        "Appoint ou surplus",
    ]

    for cx, (label, color), desc in zip(centers, labels, descriptions):
        pdf.set_xy(cx - 13, y + 42)
        pdf.set_font("Arial", "B", 5.8)
        pdf.set_text_color(*color)
        pdf.multi_cell(26, 3.1, _tx(label), align="C")

        pdf.set_xy(cx - 13, y + 49)
        pdf.set_font("Arial", "", 5.4)
        pdf.set_text_color(*TEXT)
        pdf.multi_cell(26, 3.0, _tx(desc), align="C")

    # Bandeau objectif
    band_y = y + h - 12
    pdf.set_draw_color(*BORDER)
    pdf.set_fill_color(*LIGHT_BG)
    pdf.rect(x + 5, band_y, w - 10, 8, style="DF")

    pdf.set_xy(x + 8, band_y + 1.3)
    pdf.set_font("Arial", "B", 6.2)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.cell(19, 5, _tx("OBJECTIF"))

    pdf.set_draw_color(*BORDER)
    pdf.line(x + 27, band_y + 1.5, x + 27, band_y + 6.5)

    pdf.set_xy(x + 30, band_y + 1.3)
    pdf.set_font("Arial", "", 5.8)
    pdf.set_text_color(*TEXT)
    pdf.cell(
        w - 38,
        5,
        _tx("Maximiser l'utilisation de votre énergie solaire et réduire les échanges avec le réseau."),
    )


def _resolve_logo_path(logo_path: str | None = None) -> str | None:
    """Return the first existing Soleol logo path, if available."""
    from pathlib import Path

    candidates = []
    if logo_path:
        candidates.append(Path(logo_path))

    candidates.extend(
        [
            Path("logo_soleol.png"),
            Path("logo_soleol.jpg"),
            Path("soleol_logo.png"),
            Path("soleol_logo.jpg"),
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _side_bar(pdf: FPDF, meta, tariff_profile: str, client_name: str = "", logo_path: str | None = None):
    pdf.set_fill_color(*DARK)
    pdf.rect(0, 0, 52, 297, style="F")

    resolved_logo = _resolve_logo_path(logo_path)
    if resolved_logo:
        pdf.image(resolved_logo, x=8, y=11, w=36)
    else:
        pdf.set_xy(8, 12)
        pdf.set_font("Arial", "B", 16)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(36, 8, "SOLEOL SA", ln=True)
        pdf.set_x(8)
        pdf.set_font("Arial", "", 8)
        pdf.set_text_color(230, 235, 240)
        pdf.cell(36, 5, "ÉNERGIE SOLAIRE", ln=True)

    pdf.set_draw_color(*SOLEOL_ORANGE)
    pdf.line(8, 60, 20, 60)

    pdf.set_xy(8, 66)
    pdf.set_font("Arial", "B", 7)
    pdf.set_text_color(255, 255, 255)
    pdf.multi_cell(
        36,
        4.5,
        _tx("ETUDE DE\nDIMENSIONNEMENT\nBATTERIE"),
    )

    pdf.line(8, 84, 20, 84)

    infos = [
        ("CLIENT", client_name.strip() or "A renseigner"),
        ("GRD", tariff_profile),
        ("PÉRIODE", f"{getattr(meta, 'coverage_days', 0):.0f} jours"),
        ("PAS DE TEMPS", f"{getattr(meta, 'dt_hours', 0) * 60:.0f} min"),
        ("SOURCE", getattr(meta, "vendor", "")),
    ]

    y = 92
    for label, val in infos:
        pdf.set_xy(8, y)
        pdf.set_font("Arial", "B", SIDEBAR_LABEL_SIZE)
        pdf.set_text_color(*SOLEOL_ORANGE)
        pdf.cell(36, 4, _tx(label), ln=True)

        pdf.set_x(8)
        pdf.set_font("Arial", "", SIDEBAR_VALUE_SIZE)
        pdf.set_text_color(255, 255, 255)
        pdf.multi_cell(36, 4, _tx(val))
        y += 17

    pdf.line(8, 180, 20, 180)

    pdf.set_xy(8, 214)
    pdf.set_font("Arial", "B", 9)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.multi_cell(
        36,
        4,
        _tx("L'énergie d'aujourd'hui,\noptimisée\npour demain."),
        align="L",
    )


def _plot_gain(frontier: pd.DataFrame, best, rec_gain_max: float) -> BytesIO:
    f = frontier.copy()
    fig, ax = plt.subplots(figsize=(11.0, 3.6))
    ax.plot(
        f.Cap_kWh,
        f.Import_avoided_kWh,
        "-o",
        lw=2.6,
        color="#1565C0",
        markerfacecolor="#1565C0",
        markeredgecolor="#1565C0",
    )
    ax.axvline(float(best.Cap_kWh), color="#6b7280", ls="--", lw=1.1)
    ax.scatter(
        [float(best.Cap_kWh)],
        [float(best.Import_avoided_kWh)],
        s=95,
        zorder=3,
        color="#1565C0",
    )
    ax.set_title("Énergie valorisée selon la capacité batterie", fontsize=11, weight="bold")
    ax.set_xlabel("Capacité batterie (kWh)", fontsize=9, labelpad=8)
    ax.set_ylabel("Import evité (kWh/an)", fontsize=9)
    ax.grid(alpha=0.22)
    ax.tick_params(axis="both", labelsize=8)
    ax.annotate(
        f"{best.Cap_kWh:.0f} kWh\n{best.Import_avoided_kWh:.0f} kWh/an",
        xy=(float(best.Cap_kWh), float(best.Import_avoided_kWh)),
        xytext=(10, 20),
        textcoords="offset points",
        fontsize=8,
        bbox=dict(boxstyle="round", fc="#fff4ef", ec="#e94e35", alpha=0.95),
        arrowprops=dict(arrowstyle="->", color="#e94e35"),
    )
    fig.tight_layout(pad=1.4)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight", pad_inches=0.16)
    plt.close(fig)
    buf.seek(0)
    return buf


MONTH_LABELS_FR = [
    "Janvier",
    "Fevrier",
    "Mars",
    "Avril",
    "Mai",
    "Juin",
    "Juillet",
    "Aout",
    "Septembre",
    "Octobre",
    "Novembre",
    "Decembre",
]


def _monthly_before_after(df, sim) -> pd.DataFrame:
    """Monthly import/export table, always ordered from January to December."""
    data = pd.DataFrame(
        {
            "Import avant": df.import_kWh.values,
            "Import apres": sim.import_after,
            "Export avant": df.export_kWh.values,
            "Export apres": sim.export_after,
        },
        index=pd.to_datetime(df.timestamp),
    )

    monthly = data.groupby(data.index.month).sum()
    monthly = monthly.reindex(range(1, 13), fill_value=0.0)
    monthly.index = MONTH_LABELS_FR
    return monthly


def _plot_monthly_import(df, sim) -> BytesIO:
    s = _monthly_before_after(df, sim)

    fig, ax = plt.subplots(figsize=(11.0, 3.0))
    ax.plot(
        s.index,
        s["Import avant"],
        marker="o",
        lw=2.5,
        color="#1565C0",
        markerfacecolor="#1565C0",
        markeredgecolor="#1565C0",
        label="Import avant batterie",
    )
    ax.plot(
        s.index,
        s["Import apres"],
        marker="o",
        lw=2.5,
        color="#FB8C00",
        markerfacecolor="#FB8C00",
        markeredgecolor="#FB8C00",
        label="Import apres batterie",
    )
    ax.set_ylabel("kWh/mois", fontsize=9)
    ax.set_title("Import réseau mensuel avant / apres batterie", fontsize=11, weight="bold", pad=10)
    ax.legend(ncol=2, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.22), frameon=False)
    ax.grid(alpha=0.18)
    ax.tick_params(axis="x", rotation=0, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    fig.tight_layout(pad=1.4)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    buf.seek(0)
    return buf


def _plot_monthly_export(df, sim) -> BytesIO:
    s = _monthly_before_after(df, sim)

    fig, ax = plt.subplots(figsize=(11.0, 3.0))
    ax.plot(
        s.index,
        s["Export avant"],
        marker="o",
        lw=2.5,
        color="#2E7D32",
        markerfacecolor="#2E7D32",
        markeredgecolor="#2E7D32",
        label="Export avant batterie",
    )
    ax.plot(
        s.index,
        s["Export apres"],
        marker="o",
        lw=2.5,
        color="#D32F2F",
        markerfacecolor="#D32F2F",
        markeredgecolor="#D32F2F",
        label="Export apres batterie",
    )
    ax.set_ylabel("kWh/mois", fontsize=9)
    ax.set_title("Export réseau mensuel avant / apres batterie", fontsize=11, weight="bold", pad=10)
    ax.legend(ncol=2, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.22), frameon=False)
    ax.grid(alpha=0.18)
    ax.tick_params(axis="x", rotation=0, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    fig.tight_layout(pad=1.4)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    buf.seek(0)
    return buf

def _page_1(pdf, df, meta, best, big, sim, tariff_profile, gain_share, gain_max_extra, client_name="", logo_path=None):
    pdf.add_page()
    _side_bar(pdf, meta, tariff_profile, client_name=client_name, logo_path=logo_path)

    x0 = 58
    pdf.set_xy(x0, 14)
    pdf.set_font("Arial", "B", 17)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.cell(140, 8, _tx("SYNTHESE ÉNERGÉTIQUE"), ln=True)

    import_after = sim.import_after_total
    export_after = sim.export_after_total
    import_avoided = sim.import_avoided
    export_avoided = sim.export_stored
    import_reduc = _safe_pct(import_avoided, sim.import_before)
    export_reduc = _safe_pct(export_avoided, sim.export_before)


    # Mise en page des indicateurs
    # Les cartes sont légèrement plus larges et les espacements uniformes.
    w = 35
    gap = 2
    h_top = 31
    h_small = 27

    # Ligne 1 : caractéristiques principales
    y_top = 30
    _metric_box(
        pdf, x0, y_top, w, h_top,
        "Capacité\nrecommandée",
        f"{best.Cap_kWh:.0f} kWh",
        color=BLUE,
        label_size=6.8,
        value_size=14,
    )
    _metric_box(
        pdf, x0 + (w + gap), y_top, w, h_top,
        "Puissance de charge",
        f"{best.Power_kW:.0f} kW",
        color=BLUE,
        label_size=7.0,
        value_size=14,
    )
    _metric_box(
        pdf, x0 + 2 * (w + gap), y_top, w, h_top,
        "Cycles",
        f"{best.Cycles_per_year:.0f}/an",
        "équivalents",
        color=PURPLE,
        value_size=14,
    )
    _metric_box(
        pdf, x0 + 3 * (w + gap), y_top, w, h_top,
        "Autoconsommation",
        f"+{sim.surplus_captured:.0%}",
        "",
        color=ORANGE,
        label_size=6,
        value_size=14,
    )

    # Ligne 2 : imports et énergie valorisée
    y_import = 67
    _flow_metric_box(
        pdf, x0, y_import, w, h_small,
        "Import avant",
        f"{_kwh(sim.import_before)} kWh",
        "Depuis le réseau",
        color=BLUE,
    )
    _flow_metric_box(
        pdf, x0 + (w + gap), y_import, w, h_small,
        "Import après",
        f"{_kwh(import_after)} kWh",
        "Depuis le réseau",
        color=BLUE,
    )
    _flow_metric_box(
        pdf, x0 + 2 * (w + gap), y_import, w, h_small,
        "Import évité",
        f"{_kwh(import_avoided)} kWh",
        f"-{import_reduc:.0f} %",
        color=GREEN,
    )

    valorisation_energetique = import_avoided + export_avoided
    energy_x = x0 + 3 * (w + gap)
    energy_y = y_import
    energy_h = 61

    pdf.set_draw_color(*GREEN)
    pdf.set_fill_color(*LIGHT_GREEN)
    pdf.rect(energy_x, energy_y, w, energy_h, style="DF")

    pdf.set_xy(energy_x + 4, energy_y + 7)
    pdf.set_font("Arial", "B", 8)
    pdf.set_text_color(*GREEN)
    pdf.multi_cell(w - 8, 4, _tx("ÉNERGIE\nVALORISÉE"), align="C")

    pdf.set_draw_color(*GREEN)
    pdf.line(energy_x + 5, energy_y + 21, energy_x + w - 5, energy_y + 21)

    # Chiffre principal très visible, unité séparée.
    pdf.set_xy(energy_x + 3, energy_y + 27)
    pdf.set_font("Arial", "B", 18)
    pdf.set_text_color(*GREEN)
    pdf.cell(w - 6, 9, _tx(_kwh(valorisation_energetique)), align="C")

    pdf.set_xy(energy_x + 3, energy_y + 37)
    pdf.set_font("Arial", "B", 9)
    pdf.set_text_color(*GREEN)
    pdf.cell(w - 6, 6, "kWh", align="C")

    pdf.set_xy(energy_x + 5, energy_y + 47)
    pdf.set_font("Arial", "", 6.8)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(w - 10, 4, _tx("Import évité\n+\nexport évité"), align="C")

    # Ligne 3 : exports
    y_export = 101
    _flow_metric_box(
        pdf, x0, y_export, w, h_small,
        "Export avant",
        f"{_kwh(sim.export_before)} kWh",
        "Vers le réseau",
        color=ORANGE,
    )
    _flow_metric_box(
        pdf, x0 + (w + gap), y_export, w, h_small,
        "Export après",
        f"{_kwh(export_after)} kWh",
        "Vers le réseau",
        color=ORANGE,
    )
    _flow_metric_box(
        pdf, x0 + 2 * (w + gap), y_export, w, h_small,
        "Export évité",
        f"{_kwh(export_avoided)} kWh",
        f"-{export_reduc:.0f} %",
        color=GREEN,
    )

    conclusion = (
        f"Une batterie de {best.Cap_kWh:.0f} kWh permet de valoriser environ "
        f"{_kwh(valorisation_energetique)} kWh d'énergie solaire par an, en réduisant "
        f"les achats d'électricité de {_kwh(import_avoided)} kWh et les injections réseau "
        f"de {_kwh(export_avoided)} kWh."
    )
    _info_box(pdf, x0, 138, 144, 22, "CONCLUSION", conclusion, fill=(255, 251, 249), border=SOLEOL_ORANGE)

    pdf.set_xy(x0, 170)
    pdf.set_font("Arial", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(145, 4, _tx("Les résultats sont basés sur les mesures réelles import/export et les tarifs renseignés. Les valeurs sont arrondies."))


    # Schéma vectoriel ajouté dans l'espace libre de la page 1.
    # Il est volontairement indépendant des données afin de garder un rendu stable.
    _battery_flow_diagram(pdf, x0, 190, 144, 68)


def _page_2(pdf, df, meta, rec, best, big, sim):
    pdf.add_page()
    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(*TEXT)
    pdf.cell(0, 9, _tx("Graphiques principaux"), ln=True)

    gain = _plot_gain(rec.frontier, best, rec.gain_max)
    monthly_import = _plot_monthly_import(df, sim)
    monthly_export = _plot_monthly_export(df, sim)

    # Hauteurs forcees pour eviter que le premier graphique ne masque son axe X
    # et pour garantir trois graphiques lisibles sur une page A4.
    pdf.image(gain, x=10, y=22, w=188, h=72)
    pdf.image(monthly_import, x=10, y=101, w=188, h=62)
    pdf.image(monthly_export, x=10, y=181, w=188, h=62)

    pdf.set_xy(10, 275)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(188, 4, _tx("Le graphique principal montre l'énergie achetée au réseau qui peut etre evitée selon la capacité batterie. Les deux courbes mensuelles separent l'effet de la batterie sur l'import et sur l'export réseau."))


def _page_3(pdf, df, meta, best, sim, tariff_profile, tariff_import_ht, tariff_import_bt, tariff_export):
    pdf.add_page()
    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.cell(0, 9, _tx("ANALYSE TECHNIQUE"), ln=True)

    pdf.set_draw_color(*BORDER)
    pdf.line(10, 20, 198, 20)

    import_after = sim.import_after_total
    export_after = sim.export_after_total
    import_avoided = sim.import_avoided
    export_avoided = sim.export_stored
    import_reduc = _safe_pct(import_avoided, sim.import_before)
    export_reduc = _safe_pct(export_avoided, sim.export_before)

    _info_box(
        pdf, 10, 28, 90, 39,
        "FLUX RÉSEAU",
        f"Import avant : {_kwh(sim.import_before)} kWh\n"
        f"Import après : {_kwh(import_after)} kWh\n"
        f"Import évité : {_kwh(import_avoided)} kWh (-{import_reduc:.0f}%)\n"
        f"Export évité : {_kwh(export_avoided)} kWh (-{export_reduc:.0f}%)",
        fill=LIGHT_BG,
        border=BLUE,
    )

    _info_box(
        pdf, 108, 28, 90, 39,
        "BATTERIE",
        f"Capacité nominale : {best.Cap_kWh:.0f} kWh\n"
        f"Puissance : {best.Power_kW:.0f} kW\n"
        f"Cycles équivalents : {best.Cycles_per_year:.0f} cycles/an\n"
        f"Capacité utile : {getattr(sim, 'usable_capacity_kWh', best.Cap_kWh):.1f} kWh",
        fill=LIGHT_GREEN,
        border=GREEN,
    )

    _info_box(
        pdf, 10, 76, 188, 26,
        "HYPOTHÈSES",
        f"Profil GRD : {tariff_profile} | Pas de temps : {meta.dt_hours * 60:.0f} min | "
        f"Couverture : {meta.coverage_days:.0f} jours\n"
        f"Tarifs : HT {tariff_import_ht:.2f}, BT {tariff_import_bt:.2f}, "
        f"rachat {tariff_export:.2f} CHF/kWh.",
        fill=LIGHT_ORANGE,
        border=SOLEOL_ORANGE,
    )

    _info_box(
        pdf, 10, 111, 188, 42,
        "LECTURE DES RÉSULTATS",
        f"La batterie réduit les achats réseau de {import_reduc:.0f}% et l'injection de "
        f"{export_reduc:.0f}%. Elle valorise {_kwh(export_avoided)} kWh/an de surplus solaire "
        f"avec environ {best.Cycles_per_year:.0f} cycles équivalents par an. "
        "La capacité retenue correspond au meilleur compromis entre énergie valorisée, "
        "puissance disponible et utilisation annuelle.",
        fill=LIGHT_BG,
        border=BLUE,
    )

    _info_box(
        pdf, 10, 162, 188, 38,
        "POINTS D'ATTENTION",
        "Les résultats dépendent du profil quart-horaire mesuré, des tarifs d'achat et de reprise, "
        "du rendement de la batterie et de la capacité utile retenue. Une évolution importante "
        "de la consommation ou de la production photovoltaïque peut modifier le dimensionnement optimal.",
        fill=LIGHT_ORANGE,
        border=SOLEOL_ORANGE,
    )


def generate_battery_report(
    *,
    df,
    meta,
    rec,
    best,
    big,
    sim,
    brand,
    tariff_profile: str,
    tariff_import_ht: float,
    tariff_import_bt: float,
    tariff_export: float,
    gain_share: float,
    gain_max_extra: float,
    cost_life: float = 13,
    sections=None,
    swissolar=None,
    logo_path: str | None = None,
    client_name: str = "",
) -> bytes:
    pdf = ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=12)

    _page_1(
        pdf, df, meta, best, big, sim, tariff_profile,
        gain_share, gain_max_extra,
        client_name=client_name,
        logo_path=logo_path,
    )
    _page_2(pdf, df, meta, rec, best, big, sim)
    _page_3(pdf, df, meta, best, sim, tariff_profile, tariff_import_ht, tariff_import_bt, tariff_export)

    return _pdf_bytes(pdf)
