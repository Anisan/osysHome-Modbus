from app.database import Column, SurrogatePK, db

class Tag(SurrogatePK, db.Model):
    __tablename__ = 'modbus_tags'
    title = Column(db.String(100))
    value = Column(db.String(255))
    value_original = Column(db.String(255))
    device_id = Column(db.Integer)
    request_type = Column(db.String(25))
    request_start = Column(db.Integer)
    request_total = Column(db.Integer)
    bit_order = Column(db.String(10))
    converter = Column(db.String(100))
    multiplier = Column(db.Integer)
    pool_period = Column(db.Integer)
    linked_object = Column(db.String(100))
    linked_property = Column(db.String(100))
    only_changed = Column(db.Boolean)
    checked = Column(db.DateTime)
