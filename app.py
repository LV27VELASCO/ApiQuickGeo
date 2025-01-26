import os

import folium
import phonenumbers
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from phonenumbers import carrier, geocoder
from pydantic import ValidationError
from vonage import Auth, Vonage
from vonage_sms import SmsMessage, SmsResponse

from models import PhoneNumberInput, PhoneNumberOut, SendSmsInput, SendSmsOut, SaveLocationInput, SaveLocationOut

load_dotenv()


app = Flask(__name__)
# Habilitar CORS para todas las rutas
CORS(app, resources={ r"/*": {"origins": ["http://localhost:4200", "http://127.0.0.1:5500","https://fullgeoclone.netlify.app"]}})

@app.route('/api/phone-info', methods=['POST'])
def get_phone_info():
    try:
        # Validamos los datos de entrada con Pydantic
        data = PhoneNumberInput.parse_obj(request.json)
        code = data.code
        phone_number = data.phone_number
        code_lang = data.code_lang

        # Procesamos el número telefónico con phonenumbers
        parsed_number = phonenumbers.parse(f"{code}{phone_number}")
        
        # Obtenemos el país y operador
        country = geocoder.description_for_number(parsed_number, code_lang)  # País en inglés
        operator = carrier.name_for_number(parsed_number, code_lang)  # Operador en inglés

        # Modelo de salida
        response = PhoneNumberOut(country=country, operator=operator)
        return jsonify(response.model_dump()), 200

    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except phonenumbers.phonenumberutil.NumberParseException as e:
        return jsonify({"error": f"Invalid phone number: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.route('/api/send-sms', methods=['POST'])
def send_sms():
    try:
        # Validamos los datos de entrada con Pydantic
        data = SendSmsInput.model_validate(request.json)
        code = data.code
        phone_number = data.phone_number
        
        API_KEY = os.environ.get("API_KEY")
        API_SECRET = os.environ.get("API_SECRET")
        BRAND_NAME = os.environ.get("BRAND_NAME")
        client = Vonage(Auth(api_key=API_KEY, api_secret=API_SECRET))

        # Procesamos el número telefónico con phonenumbers
        parsed_number = phonenumbers.parse(f"{code}{phone_number}")
        print(parsed_number)
        
        message = SmsMessage(
            to=parsed_number,
            from_=BRAND_NAME,
            text="Localiza tu telefono aquí: .",
            )
        
        response: SmsResponse = client.sms.send(message)

        if hasattr(response, "messages") and len(response.messages) > 0:
            # Acceder al primer mensaje en la lista
            message = response.messages[0]
            if message.status == "0":
                # Modelo de salida
                response = SendSmsOut(status=True, description="Sms enviado correctamente")
                return jsonify(response.model_dump()), 200
            else:
                response = SendSmsOut(status=False, description="No se pudo enviar correctamente el mensaje")
                return jsonify(response.model_dump()), 400
        else:
            response = SendSmsOut(status=False, description="Ocurrió un error en el envio del mensaje")
            return jsonify(response.dict()), 500
        
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/save-location', methods=['POST'])
def save_location():
    data = SaveLocationInput.model_validate(request.json)
    user_id = data.user_id
    latitude = data.latitude
    longitude = data.longitude
    timestamp = data.timestamp
    
    print(user_id,latitude,longitude,timestamp)
    response = SaveLocationOut(code="00", description="Datos recibidos")
    return jsonify(response.model_dump()), 200
    
    
if __name__ == '__main__':
    app.run(debug=True)