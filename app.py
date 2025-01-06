import folium
from opencage.geocoder import OpenCageGeocode
from flask import Flask, request, jsonify
from pydantic import BaseModel, ValidationError
import phonenumbers
from phonenumbers import geocoder, carrier, timezone
from flask_cors import CORS

app = Flask(__name__)
# Habilitar CORS para todas las rutas
CORS(app, resources={ r"/*": {"origins": ["http://localhost:4200"]}})

# Modelo de entrada
class PhoneNumberInput(BaseModel):
    code:str
    phone_number: str
    code_lang: str

# Modelo de salida
class PhoneNumberInfo(BaseModel):
    country: str
    operator: str

@app.route('/phone-info', methods=['POST'])
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
        response = PhoneNumberInfo(country=country, operator=operator)
        return jsonify(response.dict()), 200

    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except phonenumbers.phonenumberutil.NumberParseException as e:
        return jsonify({"error": f"Invalid phone number: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)