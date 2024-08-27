from app.database import Column, SurrogatePK, db

class Device(SurrogatePK, db.Model):
    __tablename__ = 'modbus_devices'
    title = Column(db.String(100))
    host = Column(db.String(100))
    port = Column(db.Integer)
    protocol = Column(db.String(5), default="TCP")
    slave = Column(db.Integer)
