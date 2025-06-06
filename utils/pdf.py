from weasyprint import HTML

def generate_pdf(html):
    return HTML(string=html).write_pdf()