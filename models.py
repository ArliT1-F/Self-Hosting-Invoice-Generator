from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_name = db.Column(db.String(100))
    client_email = db.Column(db.String(100))
    client_address = db.Column(db.Text)
    tax = db.Column(db.Float)
    items = db.relationship('Item', backref='invoice', cascade="all, delete")

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200))
    quantity = db.Column(db.Integer)
    rate = db.Column(db.Float)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
