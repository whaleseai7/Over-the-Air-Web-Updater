from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask import redirect, url_for
from flask import send_file, abort
import os
import json
import pytz

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root@localhost/my_app'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'firmware_uploaded')
app.config['ALLOWED_EXTENSIONS'] = {'bin'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mac_address = db.Column(db.String(17), unique=True, nullable=False)
    label = db.Column(db.String(100))

class FirmwareHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('device.id'), nullable=False)
    file_name = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    device = db.relationship('Device', backref=db.backref('firmware_history', lazy=True))

firmware_uploaded_dir = 'firmware_uploaded'
if not os.path.exists(firmware_uploaded_dir):
    os.makedirs(firmware_uploaded_dir)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register_device():
    mac_address = request.form.get('mac_address')
    label = request.form.get('label')

    if mac_address:
        new_device = Device(mac_address=mac_address, label=label)
        db.session.add(new_device)
        db.session.commit()
        return f"Device with MAC address {mac_address} registered with label '{label}'"
    else:
        return "Invalid request"

@app.route('/update', methods=['GET'])
def update_firmware():
    if len(request.args) > 1 or 'mac_address' not in request.args:
        return jsonify({'error': 'Invalid request parameters'}), 400

    mac_address_param = request.args.get('mac_address')

    if mac_address_param:
        device = Device.query.filter_by(mac_address=mac_address_param).first()

        if device:
            latest_firmware_entry = FirmwareHistory.query.filter_by(device_id=device.id).order_by(FirmwareHistory.timestamp.desc()).first()

            if latest_firmware_entry:
                sanitized_mac_address = device.mac_address.replace(':', '_')
                version = str(extract_version_from_filename(latest_firmware_entry.file_name))
                filename = f"{sanitized_mac_address}_{latest_firmware_entry.timestamp.strftime('%Y%m%d_%H%M%S')}_firmware_v{version}.bin"
                firmware_url = url_for('uploaded_file', filename=filename, _external=True)

                response = {'version': version, 'url': firmware_url}
                return jsonify(response)
            else:
                return jsonify('No firmware history available'), 404
        else:
            return jsonify({'error': 'Unauthorized Device'}), 401
    else:
        return jsonify({'error': 'Invalid request'}), 400

@app.route('/devices')
def list_devices():
    devices = Device.query.all()
    return render_template('devices.html', devices=devices)

@app.route('/upload', methods=['POST'])
def upload_firmware():
    selected_devices_json = request.form.get('selectedDevices')
    
    if selected_devices_json:
        selected_devices = json.loads(selected_devices_json)

        if 'firmware' in request.files:
            firmware_file = request.files['firmware']

            if firmware_file.filename != '':
                version = extract_version_from_filename(firmware_file.filename)

                if version is not None:
                    for mac_address in selected_devices:
                        device = Device.query.filter_by(mac_address=mac_address).first()

                        if device:
                            # Generate nama unik dengan menambahkan tanggal dan waktu saat ini
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"{mac_address.replace(':', '_')}_{timestamp}_firmware_v{version}.bin"

                            # Atur zona waktu ke Asia/Jakarta
                            jakarta_tz = pytz.timezone('Asia/Jakarta')
                            now_jakarta = datetime.now(jakarta_tz)

                            # Simpan waktu dalam zona waktu Jakarta
                            history_entry = FirmwareHistory(device_id=device.id, file_name=firmware_file.filename, timestamp=now_jakarta)
                            db.session.add(history_entry)
                            db.session.commit()

                            firmware_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

                        else:
                            return f"Device with MAC address {mac_address} not found", 404

                    return f"Firmware uploaded for device with MAC address {mac_address} and version {version}", 200
                else:
                    return "Invalid firmware version in filename", 400
            else:
                return "No firmware file uploaded", 400
        else:
            return "Invalid request", 400
    else:
        return "No devices selected", 400

def extract_version_from_filename(filename):
    try:    
        start_index = filename.find('_v') + 2
        end_index = filename.find('.bin')
        version_str = filename[start_index:end_index]
    
        version = int(version_str)
        return version
    except ValueError:
        return None

@app.route('/delete_device', methods=['POST'])
def delete_selected_devices():
    data = request.json

    if 'devicesToDelete' in data:
        devices_to_delete = data['devicesToDelete']

        for mac_address in devices_to_delete:
            device = Device.query.filter_by(mac_address=mac_address).first()

            if device:
                # Hapus riwayat pembaruan firmware terkait
                history_entries = FirmwareHistory.query.filter_by(device_id=device.id).all()
                for entry in history_entries:
                    sanitized_mac_address = entry.device.mac_address.replace(':', '_')
                    filename = f"{sanitized_mac_address}_{entry.file_name}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    db.session.delete(entry)

                db.session.delete(device)
                db.session.commit()
            else:
                return jsonify({'error': f'Device with MAC address {mac_address} not found'}), 404

        return '', 200
    else:
        return jsonify({'error': 'No devices to delete specified'}), 400

@app.route('/history', methods=['GET'])
def firmware_history():
    mac_address = request.args.get('mac_address')

    if mac_address:
        device = Device.query.filter_by(mac_address=mac_address).first()

        if device:
            history_entries = FirmwareHistory.query.filter_by(device_id=device.id).order_by(FirmwareHistory.timestamp.desc()).all()
            return render_template('history.html', device=device, history_entries=history_entries, extract_version_from_filename=extract_version_from_filename)
        else:
            return "Device not registered"
    else:
        return "Invalid request"

@app.route('/delete_selected', methods=['POST'])
def delete_selected_entries():
    data = request.json

    if 'entriesToDelete' in data:
        entries_to_delete = data['entriesToDelete']

        for entry_id in entries_to_delete:
            history_entry = FirmwareHistory.query.get(entry_id)

            if history_entry:
                sanitized_mac_address = history_entry.device.mac_address.replace(':', '_')
                version = str(extract_version_from_filename(history_entry.file_name))
                # Membuat nama berkas sesuai dengan format yang diharapkan (termasuk tanggal dan waktu)
                filename = f"{sanitized_mac_address}_{history_entry.timestamp.strftime('%Y%m%d_%H%M%S')}_firmware_v{version}.bin"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                if os.path.exists(file_path):
                    os.remove(file_path)

                db.session.delete(history_entry)
                db.session.commit()
            else:
                return jsonify({'error': f'History entry with ID {entry_id} not found'}), 404

        return jsonify({'message': 'Selected entries have been deleted successfully'}), 200
    else:
        return jsonify({'error': 'No entries to delete specified'}), 400

@app.route('/firmware_uploaded/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/download/<int:entry_id>', methods=['GET'])
def download_firmware(entry_id):
    history_entry = FirmwareHistory.query.get(entry_id)

    if history_entry:
        sanitized_mac_address = history_entry.device.mac_address.replace(':', '_')
        version = str(extract_version_from_filename(history_entry.file_name))
        # Membuat nama berkas sesuai dengan format yang diharapkan (termasuk tanggal dan waktu)
        filename = f"{sanitized_mac_address}_{history_entry.timestamp.strftime('%Y%m%d_%H%M%S')}_firmware_v{version}.bin"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return abort(404)
    else:
        return abort(404)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    app.run(host='0.0.0.0', port=5000, debug=True)