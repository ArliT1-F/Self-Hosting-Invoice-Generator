from flask import Flask, render_template, request, redirect, send_file
from models import db, Invoice, Item
from utils.pdf import generate_pdf
import io

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
db.init_app(app)

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    invoices = Invoice.query.all()
    return render_template('invoices_list.html', invoices=invoices)

@app.route('/create', methods=['GET', 'POST'])
def create_invoice():
    if request.method == 'POST':
        data = request.form
        invoice = Invoice(
            client_name=data['client_name'],
            client_email=data['client_email'],
            client_address=data['client_address'],
            tax=float(data['tax']),
        )
        db.session.add(invoice)
        db.session.commit()

        for desc, qty, rate in zip(request.form.getlist('desc'), request.form.getlist('qty'), request.form.getlist('rate')):
            item = Item(description=desc, quantity=int(qty), rate=float(rate), invoice_id=invoice.id)
            db.session.add(item)

        db.session.commit()
        return redirect('/')
    return render_template('create_invoice.html')


@app.route('/invoice/<int:invoice_id>/pdf')
def download_pdf(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    html = render_template('invoice_pdf.html', invoice=invoice)
    pdf = generate_pdf(html)
    return send_file(io.BytesIO(pdf), download_name=f'invoice_{invoice.id}.pdf', as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True)