""" 
# Modbus TCP


"""
import time
import datetime
from flask import redirect, render_template, jsonify, request
from sqlalchemy import delete, or_
from app.database import session_scope, row2dict, get_now_to_utc
from app.core.main.BasePlugin import BasePlugin
from plugins.Modbus.models.Device import ModbusDevice
from plugins.Modbus.models.Tags import ModbusTag
from app.authentication.handlers import handle_admin_required
from app.core.lib.object import setProperty, updateProperty, setLinkToObject, removeLinkFromObject
import pymodbus.client as ModbusClient
from pymodbus import (
    ExceptionResponse,
    FramerType,
    ModbusException
)
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder, BinaryPayloadBuilder

class Modbus(BasePlugin):

    def __init__(self, app):
        super().__init__(app, __name__)
        self.title = "Modbus"
        self.description = """Modbus protocol"""
        self.system = True
        self.actions = ['cycle','search']
        self.category = "Devices"
        self.version = "0.1"
        self.sock = None
        self.latest_data_received = time.time()

    def initialization(self):
        pass

    def admin(self, request):
        id = request.args.get("device", None)
        op = request.args.get("op", None)
        if op == 'add' or op == 'edit':
            return render_template("modbus_device.html", id=id)

        if op == 'delete':
            with session_scope() as session:
                sql = delete(ModbusTag).where(ModbusTag.device_id == int(id))
                session.execute(sql)
                sql = delete(ModbusDevice).where(ModbusDevice.id == int(id))
                session.execute(sql)
                session.commit()
                return redirect(self.name)

        devices = ModbusDevice.query.all()
        devices = [row2dict(device) for device in devices]
        return render_template("modbus_devices.html", devices=devices)

    def route_index(self):

        @self.blueprint.route('/Modbus/device', methods=['POST'])
        @self.blueprint.route('/Modbus/device/<device_id>', methods=['GET', 'POST'])
        @handle_admin_required
        def point_modbus_device(device_id=None):
            with session_scope() as session:
                if request.method == "GET":
                    dev = ModbusDevice.get_by_id(device_id)
                    device = row2dict(dev)
                    device['tags'] = []
                    tags = ModbusTag.query.filter(ModbusTag.device_id == device_id).all()
                    for tag in tags:
                        device['tags'].append(row2dict(tag))
                    return jsonify(device)
                if request.method == "POST":
                    data = request.get_json()
                    if data['id']:
                        device = session.query(ModbusDevice).where(ModbusDevice.id == int(data['id'])).one()
                    else:
                        device = ModbusDevice()
                        session.add(device)
                        session.commit()

                    device.title = data['title']
                    device.protocol = data['protocol']
                    device.host = data['host']
                    device.port = data['port']
                    device.slave = data['slave']

                    for tag in data['tags']:
                        rec = session.query(ModbusTag).filter(ModbusTag.id == tag['id']).one_or_none()
                        if not rec:
                            rec = ModbusTag()
                            session.add(rec)
                            session.commit()
                        if "del" in tag:
                            if rec.linked_object:
                                removeLinkFromObject(rec.linked_object, rec.linked_property, self.name)
                            session.delete(rec)
                            session.commit()
                        else:
                            rec.title = tag['title']
                            rec.device_id = device.id
                            rec.request_type = tag['request_type']
                            rec.request_start = tag['request_start']
                            rec.request_total = tag['request_total']
                            rec.bit_order = tag['bit_order']
                            rec.converter = tag['converter']
                            rec.multiplier = tag['multiplier']
                            rec.pool_period = tag['pool_period']
                            rec.only_changed = tag['only_changed']

                            if rec.linked_object:
                                removeLinkFromObject(rec.linked_object, rec.linked_property, self.name)
                            rec.linked_object = tag['linked_object']
                            rec.linked_property = tag['linked_property']
                            if rec.linked_object:
                                setLinkToObject(rec.linked_object, rec.linked_property, self.name)

                    session.commit()

                    return 'Device updated successfully', 200

    def search(self, query: str) -> list:
        res = []
        devices = ModbusDevice.query.filter(ModbusDevice.title.contains(query)).all()
        for device in devices:
            res.append({"url":f'Modbus?op=edit&device={device.id}', "title":f'{device.title}', "tags":[{"name":"Modbus","color":"success"}]})
        tags = ModbusTag.query.filter(or_(ModbusTag.linked_object.contains(query),ModbusTag.linked_property.contains(query))).all()
        for device in tags:
            res.append({"url":f'Modbus?op=edit&device={device.device_id}', "title":f'{device.title}', "tags":[{"name":"Modbus","color":"success"}]})
        return res

    def cyclic_task(self):
        with session_scope() as session:
            # Текущая дата и время
            now = get_now_to_utc()

            # Получаем записи, где дата меньше текущей даты минус интервал
            tags = session.query(ModbusTag).all()  # TODO уменьшить выборку ???
            for tag in tags:
                if tag.checked and tag.checked > now - datetime.timedelta(milliseconds=tag.pool_period):
                    continue
                device = session.query(ModbusDevice).filter(ModbusDevice.id == tag.device_id).one_or_none()
                if device:
                    client = None
                    if device.protocol == 'TCP':
                        client = ModbusClient.ModbusTcpClient(
                            device.host,
                            port=device.port,
                            framer=FramerType.SOCKET,
                        )
                    elif device.protocol == 'UDP':
                        client = ModbusClient.ModbusUdpClient(
                            device.host,
                            port=device.port,
                            framer=FramerType.SOCKET,
                        )
                    elif device.protocol == 'COM':
                        client = ModbusClient.ModbusSerialClient(
                            device.host,
                            framer=FramerType.RTU,
                        )
                    client.connect()

                    try:
                        rr = None
                        if tag.request_type == 'coils':
                            rr = client.read_coils(tag.request_start, tag.request_total, slave=device.slave)
                        elif tag.request_type == 'discrete_inputs':
                            rr = client.read_discrete_inputs(tag.request_start, tag.request_total, slave=device.slave)
                        elif tag.request_type == 'holding_registers':
                            rr = client.read_holding_registers(tag.request_start, tag.request_total, slave=device.slave)
                        elif tag.request_type == 'input_registers':
                            rr = client.read_input_registers(tag.request_start, tag.request_total, slave=device.slave)

                        # TODO decoder value
                        value = str(rr.registers)
                        if tag.converter:
                            if tag.bit_order == "le":
                                decoder = BinaryPayloadDecoder.fromRegisters(rr.registers, byteorder=Endian.LITTLE, wordorder=Endian.LITTLE)
                            elif tag.bit_order == "leswap":
                                decoder = BinaryPayloadDecoder.fromRegisters(rr.registers, byteorder=Endian.BIG, wordorder=Endian.LITTLE)
                            elif tag.bit_order == "beswap":
                                decoder = BinaryPayloadDecoder.fromRegisters(rr.registers, byteorder=Endian.BIG, wordorder=Endian.BIG)
                            else:
                                decoder = BinaryPayloadDecoder.fromRegisters(rr.registers, byteorder=Endian.LITTLE, wordorder=Endian.BIG)

                            if tag.converter == 'int':
                                if tag.request_total >= 4:
                                    value = decoder.decode_64bit_int()
                                elif tag.request_total >= 2:
                                    value = decoder.decode_32bit_int()
                                else:
                                    value = decoder.decode_16bit_int()
                            elif tag.converter == 'uint':
                                if tag.request_total >= 4:
                                    value = decoder.decode_64bit_uint()
                                elif tag.request_total >= 2:
                                    value = decoder.decode_32bit_uint()
                                else:
                                    value = decoder.decode_16bit_uint()
                            elif tag.converter == 'float':
                                if tag.request_total >= 4:
                                    value = decoder.decode_64bit_float()
                                else:
                                    value = decoder.decode_32bit_float()
                            elif tag.converter == 'bool':
                                value = decoder.decode_bits()
                            elif tag.converter == 'string':
                                value = decoder.decode_string(tag.request_total).decode("utf-8")

                            if tag.multiplier > 0:
                                value = float(value) / (10 ** tag.multiplier)

                        tag.value_original = str(rr.registers)
                        tag.value = str(value)
                        tag.checked = now
                        session.commit()

                        self.logger.debug("%s %s %s %s",str(rr.registers),str(value),tag.converter,tag.bit_order)

                        if tag.linked_object and tag.linked_object:
                            if tag.only_changed:
                                updateProperty(tag.linked_object + "." + tag.linked_property, value, self.name)
                            else:
                                setProperty(tag.linked_object + "." + tag.linked_property, value, self.name)

                    except ModbusException as exc:
                        self.logger.error(f"Received ModbusException({exc}) from library")
                        client.close()

                    if rr and rr.isError():
                        self.logger.error(f"Received Modbus library error({rr})")
                        client.close()

                    if isinstance(rr, ExceptionResponse):
                        self.logger.error(f"Received Modbus library exception ({rr})")
                        # THIS IS NOT A PYTHON EXCEPTION, but a valid modbus message
                        client.close()

                    client.close()

            self.event.wait(1.0)

    def changeLinkedProperty(self, obj, prop_name, value):
        self.logger.info("PropertySetHandle: %s.%s=%s",obj,prop_name,value)
        with session_scope() as session:
            tags = session.query(ModbusTag).filter(ModbusTag.linked_object == obj, ModbusTag.linked_property == prop_name).all()
            for tag in tags:
                device = session.query(ModbusDevice).filter(ModbusDevice.id == tag.device_id).one_or_none()
                client = None
                if device.protocol == 'TCP':
                    client = ModbusClient.ModbusTcpClient(
                        device.host,
                        port=device.port,
                        framer=FramerType.SOCKET,
                    )
                elif device.protocol == 'UDP':
                    client = ModbusClient.ModbusUdpClient(
                        device.host,
                        port=device.port,
                        framer=FramerType.SOCKET,
                    )
                elif device.protocol == 'COM':
                    client = ModbusClient.ModbusSerialClient(
                        device.host,
                        framer=FramerType.RTU,
                    )
                client.connect()

                try:
                    # TODO convert value to registers
                    if tag.bit_order == "le":
                        builder = BinaryPayloadBuilder(byteorder=Endian.LITTLE, wordorder=Endian.LITTLE)
                    elif tag.bit_order == "leswap":
                        builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.LITTLE)
                    elif tag.bit_order == "beswap":
                        builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
                    else:
                        builder = BinaryPayloadBuilder(byteorder=Endian.LITTLE, wordorder=Endian.BIG)

                    if tag.converter in ['int','uint','float'] and tag.multiplier > 0:
                        value = value * (10 ** tag.multiplier)

                    if tag.converter == 'int':
                        if tag.request_total >= 4:
                            builder.add_64bit_int(value)
                        elif tag.request_total >= 2:
                            builder.add_32bit_int(value)
                        else:
                            builder.add_16bit_int(value)
                    elif tag.converter == 'uint':
                        if tag.request_total >= 4:
                            builder.add_64bit_uint(value)
                        elif tag.request_total >= 2:
                            builder.add_32bit_uint(value)
                        else:
                            builder.add_16bit_uint(value)
                    elif tag.converter == 'float':
                        if tag.request_total >= 4:
                            builder.add_64bit_float(value)
                        else:
                            builder.add_32bit_float(value)
                    elif tag.converter == 'bool':
                        builder.add_bits(value)
                    elif tag.converter == 'string':
                        builder.add_string(value)
                    else:
                        builder.add_bits(value)

                    # write registers
                    registers = builder.to_registers()
                    client.write_registers(tag.request_start, registers, slave=device.slave)

                except ModbusException as exc:
                    self.logger.error(f"Received ModbusException({exc}) from library")
                    client.close()

                client.close()
