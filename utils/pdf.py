from weasyprint import HTML

def generate_pdf(html_content):
    return HTML(string=html_content).write_pdf()