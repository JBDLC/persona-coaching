"""Génération PDF (compte rendus + facture simple)."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_session_book_pdf(patient_name: str, coach_name: str, sessions: list[dict]) -> BytesIO:
    """
    sessions: [{"date": str, "notes": str, "paid": bool}, ...]
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    story = []

    title = Paragraph(f"<b>Livre de comptes rendus — {patient_name}</b>", styles["Title"])
    story.append(title)
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(f"Coach : {coach_name}", styles["Normal"]))
    story.append(Spacer(1, 1 * cm))

    for i, s in enumerate(sessions, 1):
        story.append(Paragraph(f"<b>Séance {i} — {s.get('date', '')}</b>", styles["Heading3"]))
        paid = "Payée" if s.get("paid") else "Non payée"
        story.append(Paragraph(f"<i>Statut paiement : {paid}</i>", styles["Normal"]))
        notes = s.get("notes") or "(Aucun compte rendu)"
        story.append(Paragraph(notes.replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 0.8 * cm))

    doc.build(story)
    buf.seek(0)
    return buf


def build_invoice_pdf(
    invoice_number: str,
    coach_name: str,
    patient_name: str,
    session_date: str,
    amount: str,
    description: str = "Séance de coaching",
) -> BytesIO:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph("<b>Facture simplifiée</b>", styles["Title"]))
    story.append(Spacer(1, 0.5 * cm))
    data = [
        ["N°", invoice_number],
        ["Émetteur", coach_name],
        ["Client", patient_name],
        ["Date de prestation", session_date],
        ["Libellé", description],
        ["Montant TTC (indicatif)", amount],
    ]
    t = Table(data, colWidths=[5 * cm, 10 * cm])
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 1 * cm))
    story.append(
        Paragraph(
            "<i>Document généré par la plateforme — montants à titre indicatif.</i>",
            styles["Normal"],
        )
    )
    doc.build(story)
    buf.seek(0)
    return buf
