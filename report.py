"""Rapport PDF modulaire : mêmes résultats, hypothèses et alertes que l'interface."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from i18n import recommendation_messages, msg
from simulation import simple_payback

ROOT = Path(__file__).resolve().parent
ORANGE = (233, 78, 53)
GRAY = (85, 95, 110)
BLUE = "#2563eb"
SECTION_LABELS = {"frontier": "Dimensionnement", "payback": "Retour simple",
                  "soc": "État de charge", "cycles": "Cycles équivalents", "ba": "Flux mensuels"}


def _tx(value):
    value = str(value)
    for source, target in {"–": "-", "—": "-", "’": "'", "œ": "oe", "→": "->",
                           "≤": "<=", "≥": ">=", "≠": "différent de", "…": "...", "\u202f": " "}.items():
        value = value.replace(source, target)
    return value.encode("latin-1", "replace").decode("latin-1")


def _fmt(value, decimals=0):
    return f"{value:,.{decimals}f}".replace(",", " ")


class ReportPDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fonts = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        self.add_font("DejaVu", fname=str(fonts / "DejaVuSans.ttf"))
        self.add_font("DejaVu", style="B", fname=str(fonts / "DejaVuSans-Bold.ttf"))

    def header(self):
        self.set_fill_color(15, 21, 32)
        self.rect(0, 0, 210, 24, style="F")
        self.set_text_color(255, 255, 255)
        self.set_font("DejaVu", "B", 15)
        self.set_xy(12, 7)
        self.cell(150, 9, "SOLEOL | Calculateur de batterie")
        self.set_y(31)
        self.set_text_color(35, 35, 35)

    def footer(self):
        self.set_y(-11)
        self.set_font("DejaVu", "", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 5, _tx(f"SOLEOL - Simulation énergétique                          Page {self.page_no()} / {{nb}}"))


def _paragraph(pdf, text, size=9, color=(35, 35, 35), bold=False):
    pdf.set_x(pdf.l_margin)
    pdf.set_font("DejaVu", "B" if bold else "", size)
    pdf.set_text_color(*color)
    pdf.multi_cell(0, 4.7 if size <= 10 else 6.5, _tx(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)


def _title(pdf, title):
    _paragraph(pdf, title, 15, ORANGE, True)


def _cards(pdf, cards):
    gap, width, height = 4., 43.5, 27.
    x, y = pdf.l_margin, pdf.get_y()
    for i, (label, value, detail) in enumerate(cards):
        left = x + i * (width + gap)
        pdf.set_fill_color(247, 249, 252)
        pdf.set_draw_color(219, 225, 233)
        pdf.rect(left, y, width, height, style="DF")
        pdf.set_xy(left + 3, y + 3)
        pdf.set_font("DejaVu", "B", 7.5)
        pdf.set_text_color(*GRAY)
        pdf.cell(width - 6, 4, _tx(label))
        pdf.set_xy(left + 3, y + 10)
        pdf.set_font("DejaVu", "B", 15)
        pdf.set_text_color(37, 99, 235)
        pdf.cell(width - 6, 7, _tx(value))
        pdf.set_xy(left + 3, y + 20)
        pdf.set_font("DejaVu", "", 7.5)
        pdf.set_text_color(*GRAY)
        pdf.cell(width - 6, 4, _tx(detail))
    pdf.set_xy(x, y + height + 7)


def _table(pdf, rows, widths=(65, 121)):
    pdf.set_font("DejaVu", "", 8.5)
    pdf.set_text_color(35, 35, 35)
    with pdf.table(col_widths=widths, first_row_as_headings=False, line_height=5,
                   padding=2, borders_layout="HORIZONTAL_LINES") as table:
        for cells in rows:
            row = table.row()
            for cell in cells:
                row.cell(_tx(cell))
    pdf.ln(4)


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


def _plot(section, df, sim, rec, show_financial, capex_chf):
    fig, ax = plt.subplots(figsize=(9.3, 4.6), constrained_layout=True)
    f = rec.frontier
    if section == "frontier":
        col = "Gain_CHF" if show_financial else "Import_avoided_kWh"
        unit = "Économie sur la période (CHF)" if show_financial else "Import évité sur la période (kWh)"
        ax.plot(f.Cap_kWh, f[col], color=BLUE, label="Puissance retenue à chaque capacité")
        ax.scatter([rec.best.Cap_kWh], [rec.best[col]], color="#e94e35", zorder=3, label="Configuration étudiée")
        ax.set(xlabel="Capacité nominale (kWh)", ylabel=unit)
        ax.legend(fontsize=8)
    elif section == "cycles":
        annual = sim.annual_factor is not None
        col = "Cycles_per_year" if annual else "Cycles_period"
        ax.plot(f.Cap_kWh, f[col], color="#7e3af2")
        ax.axvline(sim.capacity_kWh, color="#e94e35", linestyle="--")
        ax.set(xlabel="Capacité nominale (kWh)", ylabel="Cycles DC sur capacité utile" + (" / an (365 jours)" if annual else " / période"))
    elif section == "soc":
        local = pd.to_datetime(df.timestamp, utc=True).dt.tz_convert("Europe/Zurich")
        ax.plot(local, sim.soc_pct, linewidth=.6, color=BLUE)
        ax.axhline(sim.soc_min_pct, color="#e94e35", linestyle="--", label=f"SOC minimum {sim.soc_min_pct:g} %")
        ax.set(ylabel="SOC (% de la capacité nominale)", xlabel="Date", ylim=(0, 103))
        ax.legend(fontsize=8)
    elif section == "ba":
        monthly = monthly_before_after(df, sim)
        x = np.arange(len(monthly))
        for offset, col, color in ((-.3, "Import avant", "#93b4f2"), (-.1, "Import après", BLUE),
                                    (.1, "Export avant", "#f9bd94"), (.3, "Export après", "#e94e35")):
            ax.bar(x + offset, monthly[col], .19, label=col, color=color)
        ax.set_xticks(x, [str(m) + ("*" if q < 1 else "") for m, q in zip(monthly.index, monthly.Completeness)], rotation=45, ha="right", fontsize=8)
        ax.set(ylabel="Énergie sur les intervalles simulés (kWh)", xlabel="Année-mois ; * données mesurées incomplètes")
        ax.legend(fontsize=8)
    elif section == "payback":
        pb = simple_payback(capex_chf, sim.gain_annual_chf)
        years = np.linspace(0, max(10., min(50., (pb or 10.) * 1.15)), 150)
        ax.plot(years, -capex_chf + years * sim.gain_annual_chf, color=BLUE)
        ax.axhline(0, color="gray", linewidth=.8)
        ax.set(xlabel="Années", ylabel="Économies cumulées moins coût installé (CHF)")
        ax.set_title("Projection simple à profil et tarifs constants", fontsize=11)
    ax.grid(alpha=.18)
    stream = BytesIO()
    fig.savefig(stream, format="png", dpi=150)
    plt.close(fig)
    stream.seek(0)
    return stream


def generate_battery_report(*, df, meta, rec, sim, assumptions, client_name="", sections=None,
                            show_financial=False, capex_chf=None, tariff_schedule=None, logo_path=None):
    sections = list(SECTION_LABELS) if sections is None else list(dict.fromkeys(sections))
    if any(s not in SECTION_LABELS for s in sections):
        raise ValueError("Section PDF inconnue.")
    pdf = ReportPDF(unit="mm", format="A4")
    pdf.set_margins(12, 31, 12)
    pdf.set_auto_page_break(True, margin=17)
    pdf.alias_nb_pages()
    pdf.add_page()
    _title(pdf, "Synthèse énergétique")
    _paragraph(pdf, client_name or "Client non renseigné", 12, bold=True)
    _paragraph(pdf, f"Du {pd.Timestamp(meta.start).strftime('%d.%m.%Y %H:%M')} au {pd.Timestamp(meta.end).strftime('%d.%m.%Y %H:%M')} (fin exclue) | {meta.coverage_days:.2f} jours", 8.5, GRAY)
    _cards(pdf, [("CAPACITÉ NOMINALE", f"{sim.capacity_kWh:g} kWh", "Configuration étudiée"),
                 ("PUISSANCE AC", f"{sim.power_kW:g} kW", "Charge / décharge"),
                 ("SOC MINIMUM", f"{sim.soc_min_pct:g} %", "Limite choisie"),
                 ("CAPACITÉ UTILE", f"{sim.usable_capacity_kWh:g} kWh", "Au-dessus du SOC minimum")])
    _table(pdf, [("Flux sur la période", "Avant batterie", "Après batterie"),
                 ("Import réseau", f"{_fmt(sim.import_before)} kWh", f"{_fmt(sim.import_after_total)} kWh"),
                 ("Export réseau", f"{_fmt(sim.export_before)} kWh", f"{_fmt(sim.export_after_total)} kWh")], (66, 60, 60))
    _paragraph(pdf, f"Surplus capté à l'entrée de la batterie : {_fmt(sim.export_stored)} kWh ({sim.surplus_captured:.1%} du surplus). "
               f"Énergie restituée au site : {_fmt(sim.import_avoided)} kWh ({sim.import_reduction:.1%} des achats réseau initiaux).", 10, bold=True)
    _paragraph(pdf, f"Pertes de conversion : {_fmt(sim.conversion_losses_kWh, 1)} kWh. Stock utilisable final : {_fmt(sim.final_stock_kWh, 1)} kWh. Stock non transféré aux interruptions : {_fmt(sim.untransferred_stock_kWh, 1)} kWh.", 9)
    _paragraph(pdf, f"Cycles équivalents DC sur capacité utile : {sim.cycles_period:.1f} sur la période" +
               (f" ; {sim.cycles_per_year:.1f}/an sur une base de 365 jours." if sim.annual_factor is not None else ". Annualisation désactivée."), 9)
    if show_financial:
        _paragraph(pdf, "Économie financière sur la période", 11, ORANGE, True)
        _table(pdf, [("Achats HT évités", f"{_fmt(sim.gain_ht_chf, 2)} CHF"),
                     ("Achats BT évités", f"{_fmt(sim.gain_bt_chf, 2)} CHF"),
                     ("Revente abandonnée", f"{_fmt(sim.export_value_lost_chf, 2)} CHF"),
                     ("Économie nette", f"{_fmt(sim.gain_chf, 2)} CHF")])
        if sim.gain_annual_chf is not None:
            _paragraph(pdf, f"Équivalent annuel (365 jours) : {_fmt(sim.gain_annual_chf, 2)} CHF/an. Les résultats de période ci-dessus ne sont pas extrapolés.", 8.5)
    warnings = list(meta.warnings) + recommendation_messages(rec)
    _paragraph(pdf, "Dimensionnement énergétique indicatif" if rec.recommended else "Configuration d'analyse - dimensionnement non validé", 10, ORANGE, True)
    for warning in warnings[:3]:
        _paragraph(pdf, warning, 8.5, GRAY)
    if len(warnings) > 3:
        _paragraph(pdf, "Toutes les réserves figurent dans les hypothèses et le contrôle de qualité ci-après.", 8)
    # Resources are relative to this module, independent of the launch directory.
    logo = Path(logo_path) if logo_path else ROOT / "logo_soleol.png"
    if logo.is_file():
        pdf.image(str(logo), x=174, y=5, w=23, h=13, keep_aspect_ratio=True)

    pdf.add_page()
    _title(pdf, "Hypothèses et qualité des données")
    assumption_rows = list(assumptions.items())
    if not show_financial:
        assumption_rows = [(k, v) for k, v in assumption_rows if k not in {"Retour simple", "Coût installé renseigné"}]
    _table(pdf, assumption_rows)
    _paragraph(pdf, "Réserves de l'étude", 12, ORANGE, True)
    for warning in warnings:
        _paragraph(pdf, "- " + warning, 9)
    for code, params in rec.notes:
        _paragraph(pdf, msg("fr", code, params), 9)
    if meta.missing_periods:
        _paragraph(pdf, "Périodes inconnues dans la source", 11, ORANGE, True)
        _table(pdf, [(p["debut"], f"Jusqu'à {p['fin_exclue']} (exclue) ; {p['heures']:g} h") for p in meta.missing_periods])
    if tariff_schedule:
        _paragraph(pdf, "Calendrier tarifaire appliqué", 11, ORANGE, True)
        _table(pdf, [(f"{s['start']} / {s['end']} (exclu)",
                     f"HT {s['ht']:.4f}, BT {s['bt']:.4f}, reprise {s['export']:.4f} CHF/kWh ; plages {s.get('periods', ())} ; week-end BT : {s.get('weekend_low', False)}") for s in tariff_schedule])
    schema = next((ROOT / name for name in ("Schema.png", "Schema.jpg", "Schema.jpeg", "schema.png")
                   if (ROOT / name).is_file()), None)
    if schema is not None:
        pdf.add_page()
        _title(pdf, "Schéma de fonctionnement")
        pdf.image(str(schema), x=12, y=50, w=186, h=185, keep_aspect_ratio=True)
    for index, section in enumerate(sections):
        if index % 2 == 0:
            pdf.add_page()
        top = 31 if index % 2 == 0 else 156
        pdf.set_xy(12, top)
        _title(pdf, SECTION_LABELS[section])
        if section == "payback" and (not show_financial or simple_payback(capex_chf, sim.gain_annual_chf) is None):
            _paragraph(pdf, "Retour simple non calculé : il faut autoriser l'affichage financier, renseigner un coût installé et disposer d'une économie annuelle positive.")
            continue
        chart = _plot(section, df, sim, rec, show_financial, capex_chf)
        pdf.image(chart, x=12, y=top + 10, w=186)
        pdf.set_y(top + 104)
        if section == "frontier":
            _paragraph(pdf, "Point orange : configuration étudiée. La sélection repose sur les achats évités et la revente abandonnée ; aucune rentabilité n'est déduite sans coût installé.", 8.5)
        elif section == "soc":
            _paragraph(pdf, "Le stock commence au SOC minimum. Un trou non estimé interrompt la courbe ; le segment suivant repart au SOC minimum. Le stock sous cette limite reste inutilisé.", 8.5)
        elif section == "ba":
            _paragraph(pdf, "Années séparées ; * mois de mesures incomplets. Les mois absents restent sans valeur. Les sommes portent sur les intervalles simulés, estimations explicites comprises.", 8.5)
        elif section == "payback":
            _paragraph(pdf, f"Coût installé : {_fmt(capex_chf)} CHF. Retour simple : {simple_payback(capex_chf, sim.gain_annual_chf):.1f} ans. Paramètres constants, sans actualisation ni vieillissement.", 8.5)
        else:
            _paragraph(pdf, "Cycles = énergie interne déchargée (DC) / capacité utile. Les cycles sur capacité nominale restent une autre convention.", 8.5)
    return bytes(pdf.output())
