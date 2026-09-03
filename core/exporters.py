from datetime import datetime


def messages_to_markdown(title: str, messages: list[dict]) -> str:
    lines = [f"# {title}", "", f"> 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    for msg in messages:
        role = "用户" if msg["role"] == "user" else "助手"
        lines.append(f"## {role}")
        lines.append("")
        lines.append(msg["content"])
        lines.append("")
        if msg.get("sources"):
            lines.append("**引用来源**")
            lines.append("")
            for source in msg["sources"]:
                lines.append(f"- `{source['source']}`")
            lines.append("")
    return "\n".join(lines)


def suggestion_to_markdown(report_text: str) -> str:
    return (
        f"# PRD 诊断报告\n\n> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        + report_text
    )


def _escape_pdf(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def text_to_pdf_bytes(title: str, markdown_text: str) -> bytes:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    story.append(Paragraph(f"<font name='STSong-Light' size='18'>{_escape_pdf(title)}</font>"))
    story.append(Spacer(1, 18))

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            story.append(
                Paragraph(
                    f"<font name='STSong-Light' size='14'><b>{_escape_pdf(line[3:])}</b></font>",
                )
            )
        elif line.startswith("# "):
            story.append(
                Paragraph(
                    f"<font name='STSong-Light' size='16'><b>{_escape_pdf(line[2:])}</b></font>"
                )
            )
        elif line.startswith("- "):
            story.append(
                Paragraph(
                    f"<font name='STSong-Light' size='11'>• {_escape_pdf(line[2:])}</font>",
                    bulletIndent=12,
                )
            )
        elif line.startswith("**"):
            story.append(
                Paragraph(
                    f"<font name='STSong-Light' size='11'><b>{_escape_pdf(line.strip('*'))}</b></font>"
                )
            )
        else:
            story.append(
                Paragraph(
                    f"<font name='STSong-Light' size='11'>{_escape_pdf(line)}</font>"
                )
            )
        story.append(Spacer(1, 4))

    doc.build(story)
    return buffer.getvalue()
