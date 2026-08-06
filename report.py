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
        self.set_font("Arial", "", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 5, _tx(f"Battery Sizer - page {self.page_no()}"), align="C")


def _add_section_title(pdf: FPDF, title: str, x: float, y: float, w: float):
    pdf.set_xy(x, y)
    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.cell(w, 8, _tx(title), ln=False)


def _metric_box(pdf: FPDF, x: float, y: float, w: float, h: float, label: str, value: str, sub: str = "", color=BLUE):
    pdf.set_draw_color(*BORDER)
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(x, y, w, h, style="DF")
    pdf.set_xy(x + 4, y + 4)
    pdf.set_font("Arial", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(w - 8, 4, _tx(label.upper()), ln=True)
    pdf.set_xy(x + 4, y + 11)
    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(*color)
    pdf.cell(w - 8, 7, _tx(value), ln=True)
    if sub:
        pdf.set_xy(x + 4, y + h - 8)
        pdf.set_font("Arial", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.cell(w - 8, 4, _tx(sub))


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


def _side_bar(pdf: FPDF, meta, tariff_profile: str, logo_path: str | None = None):
    pdf.set_fill_color(*DARK)
    pdf.rect(0, 0, 52, 297, style="F")

    resolved_logo = _resolve_logo_path(logo_path)
    if resolved_logo:
        # Logo sur fond sombre, conserve ses proportions dans une zone de 36 x 18 mm.
        pdf.image(resolved_logo, x=8, y=11, w=36)
    else:
        # Solution de secours si aucun fichier logo n'est présent.
        pdf.set_xy(8, 12)
        pdf.set_font("Arial", "B", 16)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(36, 8, "SOLEOL SA", ln=True)
        pdf.set_x(8)
        pdf.set_font("Arial", "", 8)
        pdf.set_text_color(230, 235, 240)
        pdf.cell(36, 5, "ÉNERGIE SOLAIRE", ln=True)

    pdf.set_xy(8, 68)
    pdf.set_font("Arial", "B", 8)
    pdf.set_text_color(255, 255, 255)
    pdf.multi_cell(
        36,
        4.5,
        _tx("ETUDE DE\nDIMENSIONNEMENT\nBATTERIE"),
    )

    infos = [
        ("Client", "A renseigner"),
        ("GRD", tariff_profile),
        ("Periode", f"{getattr(meta, 'coverage_days', 0):.0f} jours"),
        ("Pas de temps", f"{getattr(meta, 'dt_hours', 0) * 60:.0f} min"),
        ("Source", getattr(meta, "vendor", "")),
    ]
    y = 84
    for label, val in infos:
        pdf.set_xy(8, y)
        pdf.set_font("Arial", "B", 7)
        pdf.set_text_color(180, 190, 200)
        pdf.cell(36, 4, _tx(label), ln=True)
        pdf.set_x(8)
        pdf.set_font("Arial", "", 8)
        pdf.set_text_color(255, 255, 255)
        pdf.multi_cell(36, 4, _tx(val))
        y += 14

    pdf.set_xy(8, 255)
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.multi_cell(36, 4, _tx("L'énergie d'aujourd'hui,\noptimisée pour demain."))


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

def _page_1(pdf, df, meta, best, big, sim, tariff_profile, gain_share, gain_max_extra, logo_path=None):
    pdf.add_page()
    _side_bar(pdf, meta, tariff_profile, logo_path=logo_path)

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


    # Main metrics
    _metric_box(pdf, x0, 30, 43, 28, "Capacité", f"{best.Cap_kWh:.0f} kWh", color=BLUE)
    _metric_box(pdf, x0 + 47, 30, 43, 28, "Puissance", f"{best.Power_kW:.0f} kW", color=BLUE)
    _metric_box(pdf, x0 + 94, 30, 50, 28, "Énergie valorisée", f"{_kwh(import_avoided)} kWh", "Achats réseau evités", color=GREEN)

    y = 67
    w = 34
    h = 26
    gap = 3
    _metric_box(pdf, x0, y, w, h, "Import avant", f"{_kwh(sim.import_before)} kWh", "Depuis le réseau", color=BLUE)
    _metric_box(pdf, x0 + (w + gap), y, w, h, "Import apres", f"{_kwh(import_after)} kWh", "Depuis le réseau", color=BLUE)
    _metric_box(pdf, x0 + 2 * (w + gap), y, w, h, "Import evité", f"{_kwh(import_avoided)} kWh", f"-{import_reduc:.0f} %", color=GREEN)
    _metric_box(pdf, x0 + 3 * (w + gap), y, w, h, "Export avant", f"{_kwh(sim.export_before)} kWh", "Vers le réseau", color=ORANGE)

    y2 = 99
    _metric_box(pdf, x0, y2, w, h, "Export apres", f"{_kwh(export_after)} kWh", "Vers le réseau", color=ORANGE)
    _metric_box(pdf, x0 + (w + gap), y2, w, h, "Export evité", f"{_kwh(export_avoided)} kWh", f"-{export_reduc:.0f} %", color=GREEN)
    _metric_box(pdf, x0 + 2 * (w + gap), y2, w, h, "Surplus capté", f"{sim.surplus_captured:.0%}", "du surplus solaire", color=ORANGE)
    _metric_box(pdf, x0 + 3 * (w + gap), y2, w, h, "Cycles", f"{best.Cycles_per_year:.0f}/an", "equivalents", color=PURPLE)

    conclusion = (
        f"Une batterie de {best.Cap_kWh:.0f} kWh permet de stocker {_kwh(export_avoided)} kWh/an de surplus solaire "
        f"et d'éviter {_kwh(import_avoided)} kWh/an d'achat réseau. "
        f"Cette capacité represente un bon compromis entre énergie valorisée et capacité installée. "
        f"Les hypotheses techniques sont indiquées dans l'analyse detaillée."
    )
    _info_box(pdf, x0, 137, 144, 34, "CONCLUSION ENERGETIQUE", conclusion)

    pdf.set_xy(x0, 184)
    pdf.set_font("Arial", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(145, 4, _tx("Les résultats sont basés sur les mesures réelles import/export et les tarifs renseignés. Les valeurs sont arrondies."))


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
    pdf.set_text_color(*TEXT)
    pdf.cell(0, 9, _tx("Analyse technique"), ln=True)

    import_after = sim.import_after_total
    export_after = sim.export_after_total
    import_avoided = sim.import_avoided
    export_avoided = sim.export_stored
    import_reduc = _safe_pct(import_avoided, sim.import_before)
    export_reduc = _safe_pct(export_avoided, sim.export_before)

    _info_box(
        pdf,
        10,
        25,
        90,
        34,
        "FLUX RÉSEAU",
        f"Import avant : {_kwh(sim.import_before)} kWh\n"
        f"Import apres : {_kwh(import_after)} kWh\n"
        f"Import evité : {_kwh(import_avoided)} kWh (-{import_reduc:.0f}%)\n"
        f"Export evité : {_kwh(export_avoided)} kWh (-{export_reduc:.0f}%)",
        fill=LIGHT_BG,
        border=BORDER,
    )

    _info_box(
        pdf,
        108,
        25,
        90,
        34,
        "BATTERIE",
        f"Capacité nominale : {best.Cap_kWh:.0f} kWh\n"
        f"Puissance : {best.Power_kW:.0f} kW\n"
        f"Cycles equivalents : {best.Cycles_per_year:.0f} cycles/an\n"
        f"Capacité utile : {getattr(sim, 'usable_capacity_kWh', best.Cap_kWh):.1f} kWh",
        fill=LIGHT_GREEN,
        border=GREEN,
    )

    _info_box(
        pdf,
        10,
        68,
        188,
        22,
        "HYPOTHESES",
        f"Profil GRD : {tariff_profile} | Pas de temps : {meta.dt_hours * 60:.0f} min | Couverture : {meta.coverage_days:.0f} jours | "
        f"Tarifs utilises dans le calcul interne : HT {tariff_import_ht:.2f}, BT {tariff_import_bt:.2f}, rachat {tariff_export:.2f} CHF/kWh.",
        fill=LIGHT_ORANGE,
        border=SOLEOL_ORANGE,
    )

    _info_box(
        pdf,
        10,
        103,
        188,
        38,
        "LECTURE DES RESULTATS",
        f"La batterie permet de reduire les achats réseau de {import_reduc:.0f}% et l'injection de {export_reduc:.0f}%. "
        f"Elle valorise {_kwh(export_avoided)} kWh/an de surplus solaire, avec environ {best.Cycles_per_year:.0f} cycles equivalents par an. "
        "La capacité retenue correspond au meilleur compromis entre l'énergie valorisée, la puissance disponible et l'utilisation annuelle de la batterie.",
        fill=LIGHT_BG,
        border=BLUE,
    )

    _info_box(
        pdf,
        10,
        151,
        188,
        34,
        "POINTS D'ATTENTION",
        "Les resultats dependent du profil quart-horaire mesure, des tarifs d'achat et de reprise, du rendement de la batterie et de la capacite utile retenue. "
        "Une evolution importante de la consommation ou de la production photovoltaïque peut modifier le dimensionnement optimal.",
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
) -> bytes:
    pdf = ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)

    _page_1(pdf, df, meta, best, big, sim, tariff_profile, gain_share, gain_max_extra, logo_path=logo_path)
    _page_2(pdf, df, meta, rec, best, big, sim)
    _page_3(pdf, df, meta, best, sim, tariff_profile, tariff_import_ht, tariff_import_bt, tariff_export)

    return _pdf_bytes(pdf)
