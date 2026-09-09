"""PDF report generation for Battery Sizer.

Creates a clean 3-page A4 report:
1. executive summary
2. charts
3. detailed analysis
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import json

ROOT = Path(__file__).resolve().parent
SECTION_LABELS = {"frontier": "Dimensionnement", "ba": "Flux mensuels"}
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


def _fit_value(pdf, value, width):
    size = pdf.font_size_pt
    while size > 7 and pdf.get_string_width(_tx(value)) > width:
        size -= .5
        pdf.set_font("Arial", "B", size)


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
    _fit_value(pdf, value, w - 8)
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


def _financial_box(
    pdf: FPDF,
    x: float,
    y: float,
    w: float,
    h: float,
    sim,
    tariff_import_ht: float,
    tariff_import_bt: float,
    tariff_export: float,
):
    """Optional financial summary for Residential, PME or C&I studies."""
    gain_ht = float(getattr(sim, "gain_ht_chf", 0.0) or 0.0)
    gain_bt = float(getattr(sim, "gain_bt_chf", 0.0) or 0.0)
    export_lost = float(getattr(sim, "export_value_lost_chf", 0.0) or 0.0)
    net_gain = float(getattr(sim, "gain_chf", gain_ht + gain_bt - export_lost) or 0.0)

    avoided_ht = float(getattr(sim, "import_avoided_ht", 0.0) or 0.0)
    avoided_bt = float(getattr(sim, "import_avoided_bt", 0.0) or 0.0)
    export_stored = float(getattr(sim, "export_stored", 0.0) or 0.0)

    pdf.set_draw_color(*GREEN)
    pdf.set_fill_color(*LIGHT_GREEN)
    pdf.rect(x, y, w, h, style="DF")

    pdf.set_xy(x + 5, y + 4)
    pdf.set_font("Arial", "B", 9)
    pdf.set_text_color(*GREEN)
    pdf.cell(w - 10, 5, _tx("ÉCONOMIE FINANCIÈRE"))

    # Partie gauche : détail du calcul.
    detail_w = 88
    pdf.set_draw_color(*BORDER)
    pdf.line(x + detail_w + 4, y + 9, x + detail_w + 4, y + h - 5)

    same_import_tariff = abs(float(tariff_import_ht) - float(tariff_import_bt)) < 1e-9
    if same_import_tariff:
        rows = [
            (
                "Achat réseau évité",
                avoided_ht + avoided_bt,
                float(tariff_import_ht),
                gain_ht + gain_bt,
            ),
            (
                "Revente non perçue",
                export_stored,
                float(tariff_export),
                -export_lost,
            ),
        ]
        row_y = [y + 13, y + 23]
    else:
        rows = [
            ("Import évité HT", avoided_ht, float(tariff_import_ht), gain_ht),
            ("Import évité BT", avoided_bt, float(tariff_import_bt), gain_bt),
            ("Revente non perçue", export_stored, float(tariff_export), -export_lost),
        ]
        row_y = [y + 12, y + 20, y + 28]

    for yy, (label, energy, tariff, value) in zip(row_y, rows):
        pdf.set_xy(x + 5, yy)
        pdf.set_font("Arial", "B", 6.4)
        pdf.set_text_color(*TEXT)
        pdf.cell(31, 4, _tx(label))

        pdf.set_xy(x + 36, yy)
        pdf.set_font("Arial", "", 6.2)
        pdf.set_text_color(*MUTED)
        pdf.cell(27, 4, _tx(f"{_kwh(energy)} kWh x {tariff:.3f}"), align="R")

        pdf.set_xy(x + 65, yy)
        pdf.set_font("Arial", "B", 6.5)
        pdf.set_text_color(*(GREEN if value >= 0 else ORANGE))
        sign = "-" if value < 0 else ""
        pdf.cell(24, 4, _tx(f"{sign}{_chf(abs(value))} CHF"), align="R")

    # Partie droite : économie nette annuelle mise en évidence.
    net_x = x + detail_w + 8
    net_w = w - detail_w - 13
    pdf.set_xy(net_x, y + 10)
    pdf.set_font("Arial", "B", 6.8)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(net_w, 3.5, _tx("ÉCONOMIE NETTE\nSUR LA PÉRIODE"), align="C")

    pdf.set_xy(net_x, y + 20)
    pdf.set_font("Arial", "B", 17)
    pdf.set_text_color(*GREEN)
    pdf.cell(net_w, 8, _tx(_chf(net_gain)), align="C")

    pdf.set_xy(net_x, y + 28)
    pdf.set_font("Arial", "B", 8)
    pdf.set_text_color(*GREEN)
    pdf.cell(net_w, 5, "CHF", align="C")

















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
        if (ROOT / candidate).is_file():
            return str(ROOT / candidate)
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
    ax.set_title("Énergie achetée évité", fontsize=12, weight="bold")
    ax.set_xlabel("Capacité batterie (kWh)", fontsize=9, labelpad=8)
    ax.set_ylabel("Import évité (kWh sur la période)", fontsize=9)
    ax.grid(alpha=0.22)
    ax.tick_params(axis="both", labelsize=8)
    ax.annotate(
        f"{best.Cap_kWh:g} kWh\n{best.Import_avoided_kWh:.0f} kWh",
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


def _monthly_before_after(df, sim):
    monthly = monthly_before_after(df, sim)
    multi_year = len(set(monthly.index.year)) > 1
    monthly.index = [MONTH_LABELS_FR[p.month - 1] + (f" {p.year}" if multi_year else "")
                     + ("*" if q < 1 else "") for p, q in zip(monthly.index, monthly.Completeness)]
    return monthly.rename(columns={"Import après": "Import apres", "Export après": "Export apres"})


def monthly_before_after(df, sim):
    local = pd.to_datetime(df.timestamp, utc=True).dt.tz_convert("Europe/Zurich")
    frame = pd.DataFrame({"month": local.dt.tz_localize(None).dt.to_period("M"),
        "Import avant": np.where(sim.valid, df.import_kWh, np.nan), "Import après": sim.import_after,
        "Export avant": np.where(sim.valid, df.export_kWh, np.nan), "Export après": sim.export_after,
        "mesure": df.valid.to_numpy(bool), "estime": df.estimated.to_numpy(bool)})
    flows = frame.groupby("month")[["Import avant", "Import après", "Export avant", "Export après"]].sum(min_count=1)
    flows["Completeness"] = frame.groupby("month").mesure.mean()
    flows["Estimated"] = frame.groupby("month").estime.sum()
    return flows


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

def _page_1(
    pdf, df, meta, best, big, sim, tariff_profile, gain_share, gain_max_extra,
    tariff_import_ht, tariff_import_bt, tariff_export, study_mode="residential",
    show_financial: bool = False,
    client_name="", logo_path=None, recommended=True,
):
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
        ("Capacité\nrecommandée" if recommended else "Capacité\nétudiée"),
        f"{best.Cap_kWh:g} kWh",
        color=BLUE,
        label_size=6.8,
        value_size=14,
    )
    _metric_box(
        pdf, x0 + (w + gap), y_top, w, h_top,
        "Puissance de charge",
        f"{best.Power_kW:g} kW",
        color=BLUE,
        label_size=7.0,
        value_size=14,
    )
    _metric_box(
        pdf, x0 + 2 * (w + gap), y_top, w, h_top,
        "Cycles",
        (f"{sim.cycles_per_year:.0f}/an" if sim.annual_factor is not None else f"{sim.cycles_period:.0f}"),
        ("équivalents DC" if sim.annual_factor is not None else "DC sur la période"),
        color=PURPLE,
        value_size=14,
    )
    _metric_box(
        pdf, x0 + 3 * (w + gap), y_top, w, h_top,
        "Surplus capté",
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

    valorisation_energetique = import_avoided
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
    _fit_value(pdf, _kwh(valorisation_energetique), w - 6)
    pdf.cell(w - 6, 9, _tx(_kwh(valorisation_energetique)), align="C")

    pdf.set_xy(energy_x + 3, energy_y + 37)
    pdf.set_font("Arial", "B", 9)
    pdf.set_text_color(*GREEN)
    pdf.cell(w - 6, 6, "kWh", align="C")

    pdf.set_xy(energy_x + 5, energy_y + 47)
    pdf.set_font("Arial", "", 6.8)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(w - 10, 4, _tx("Énergie solaire\nrestituée au site"), align="C")

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
        f"Sur la période simulée, une batterie de {best.Cap_kWh:g} kWh restitue "
        f"{_kwh(import_avoided)} kWh au site et capte {_kwh(export_avoided)} kWh de surplus solaire. "
        "Les pertes de conversion sont incluses."
    )

    financial_enabled = bool(show_financial)

    if financial_enabled:
        # Bloc financier optionnel, disponible pour Résidentiel, PME et C&I.
        _financial_box(
            pdf, x0, 138, 144, 34, sim,
            tariff_import_ht=tariff_import_ht,
            tariff_import_bt=tariff_import_bt,
            tariff_export=tariff_export,
        )
        conclusion_y = 177
        note_y = 205
        schema_y = 216
        schema_x = x0 + 7
        schema_w = 130
    else:
        # Sans bloc financier : rendu historique inchangé.
        conclusion_y = 138
        note_y = 170
        schema_y = 187
        schema_x = x0
        schema_w = 144

    _info_box(
        pdf, x0, conclusion_y, 144, 22, "CONCLUSION" if recommended else "CONFIGURATION D'ANALYSE", conclusion,
        fill=(255, 251, 249), border=SOLEOL_ORANGE,
    )

    pdf.set_xy(x0, note_y)
    pdf.set_font("Arial", "", 8.2 if financial_enabled else 10)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        145, 4,
        _tx("Les résultats sont basés sur les mesures réelles import/export et les tarifs renseignés. Les valeurs sont arrondies."),
    )


    # Schéma de fonctionnement sous forme d'image.
    # Placer le fichier Schema.png (ou Schema.jpg / Schema.jpeg) à côté de report.py.
    schema_candidates = [
        "Schema.png",
        "Schema.jpg",
        "Schema.jpeg",
        "schema.png",
        "schema.jpg",
        "schema.jpeg",
    ]
    schema_path = next((str(ROOT / p) for p in schema_candidates if (ROOT / p).is_file()), None)

    if schema_path:
        # En C&I, le schéma est légèrement réduit, sans déformer son ratio, afin de
        # laisser la place au bloc financier tout en conservant une page 1 de synthèse.
        pdf.image(schema_path, x=schema_x, y=schema_y, w=schema_w)


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
    pdf.multi_cell(188, 4, _tx("Le graphique principal montre l'énergie achetée au réseau qui peut etre evitée selon la capacité batterie. * : mois incomplet. Les deux courbes mensuelles separent l'effet de la batterie sur l'import et sur l'export réseau."))


def _technical_page(pdf, meta, rec, sim, assumptions):
    pdf.add_page()
    pdf.set_xy(10, 10)
    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.cell(0, 9, _tx("ANALYSE TECHNIQUE"), ln=True)
    pdf.set_draw_color(*BORDER)
    pdf.line(10, 20, 198, 20)
    _info_box(pdf, 10, 28, 90, 39, "FLUX RÉSEAU",
        f"Import avant : {_kwh(sim.import_before)} kWh\nImport après : {_kwh(sim.import_after_total)} kWh\n"
        f"Import évité : {_kwh(sim.import_avoided)} kWh\nExport évité : {_kwh(sim.export_stored)} kWh",
        fill=LIGHT_BG, border=BLUE)
    _info_box(pdf, 108, 28, 90, 39, "BATTERIE",
        f"Capacité nominale : {sim.capacity_kWh:g} kWh\nPuissance : {sim.power_kW:g} kW\n"
        f"Capacité utile : {sim.usable_capacity_kWh:g} kWh\nSOC minimum : {sim.soc_min_pct:g} %",
        fill=LIGHT_GREEN, border=GREEN)
    _info_box(pdf, 10, 76, 188, 26, "HYPOTHÈSES",
        f"Profil GRD : {assumptions['Profil tarifaire']} | Pas : {meta.dt_hours * 60:g} min | Période : {meta.coverage_days:g} jours\n"
        f"{assumptions['Tarifs CHF/kWh']}\nRendement aller-retour : {sim.roundtrip_eff:.0%} | Plage utilisée : {sim.soc_min_pct:g}-100 %",
        fill=LIGHT_ORANGE, border=SOLEOL_ORANGE)
    _info_box(pdf, 10, 111, 188, 42, "LECTURE DES RÉSULTATS",
        f"La batterie restitue {_kwh(sim.import_avoided)} kWh au site à partir de {_kwh(sim.export_stored)} kWh captés. "
        f"Pertes de conversion : {_kwh(sim.conversion_losses_kWh)} kWh. Stock final utilisable : {_kwh(sim.final_stock_kWh)} kWh. "
        f"Stock non transféré aux interruptions : {_kwh(sim.untransferred_stock_kWh)} kWh. "
        f"Cycles DC sur capacité utile : {sim.cycles_period:.1f} sur la période. "
        "Les résultats dépendent des mesures et des tarifs renseignés.",
        fill=LIGHT_BG, border=BLUE)
    quality = (f"Données exploitables : {meta.completeness:.2%}. {meta.invalid_rows} intervalle(s) invalide(s), "
               f"{meta.absent_rows} absent(s). ")
    if meta.blank_zero_cells:
        quality += f"Groupe E : {meta.blank_zero_cells} cellules vides supposées nulles si l'autre flux est mesuré. "
    if any("première occurrence" in w for w in meta.warnings):
        quality += "Heure d'automne isolée : première occurrence (été), convention automatique. "
    elif any("seconde occurrence" in w for w in meta.warnings):
        quality += "Heure d'automne isolée : seconde occurrence (hiver). "
    if meta.missing_policy == "segments":
        quality += f"Segments indépendants ; SOC initial {sim.soc_min_pct:g} %. Les valeurs inconnues sont exclues. "
    elif meta.estimated_rows:
        quality += f"{meta.estimated_rows} intervalles estimés par jours comparables. "
    quality += ("Dimensionnement indicatif." if rec.recommended else "Configuration d'analyse, dimensionnement non validé.")
    _info_box(pdf, 10, 162, 188, 38, "POINTS D'ATTENTION", quality, fill=LIGHT_ORANGE, border=SOLEOL_ORANGE)



def generate_battery_report(*, df, meta, rec, sim, assumptions, client_name="", sections=None,
                            show_financial=False, capex_chf=None, tariff_schedule=None, logo_path=None):
    """Three original pages; corrections alter values and wording, never the layout."""
    if sections is not None and list(sections) != ["frontier", "ba"]:
        raise ValueError("Le rapport conserve ses trois pages et graphiques d'origine.")
    pdf = ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=12)
    ht = sim.gain_ht_chf / sim.import_avoided_ht if sim.import_avoided_ht else 0.
    bt = sim.gain_bt_chf / sim.import_avoided_bt if sim.import_avoided_bt else 0.
    ex = sim.export_value_lost_chf / sim.export_stored if sim.export_stored else 0.
    _page_1(pdf, df, meta, rec.best, rec.max_gain_pick, sim, assumptions["Profil tarifaire"], 0., 0.,
            ht, bt, ex, study_mode=rec.study_mode, show_financial=show_financial,
            client_name=client_name, logo_path=logo_path, recommended=rec.recommended)
    _page_2(pdf, df, meta, rec, rec.best, rec.max_gain_pick, sim)
    _technical_page(pdf, meta, rec, sim, assumptions)
    # Full provenance travels with the PDF without adding or rearranging visible pages.
    audit = {"hypotheses": assumptions, "avertissements": meta.warnings,
             "periodes_inconnues": meta.missing_periods, "calendrier_tarifaire": tariff_schedule,
             "dimensionnement": {"avertissements": rec.warnings, "notes": rec.notes}}
    pdf.embed_file(bytes=json.dumps(audit, ensure_ascii=False, indent=2).encode(),
                   basename="hypotheses_et_qualite.json", mime_type="application/json")
    return _pdf_bytes(pdf)
