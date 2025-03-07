import os
import json
import random
import string
import phonenumbers
from dotenv import load_dotenv
from flask import Flask, jsonify, json, request
from flask_cors import CORS
from phonenumbers import carrier, geocoder
from pydantic import ValidationError
from vonage import Auth, Vonage
from vonage_sms import SmsMessage, SmsResponse
from jinja2 import Environment, FileSystemLoader
from models import CreateUserInput, CreateUserOut, PhoneNumberInput, PhoneNumberOut, SendSmsInput, SendSmsOut, SaveLocationInput, SaveLocationOut, AccountVerificationInput, AccountVerificationOut
from supabase import create_client, Client
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import stripe

load_dotenv()


app = Flask(__name__)
# Habilitar CORS para todas las rutas
# Configuración de CORS
CORS(app, resources={
    r"/*": {
        "origins": ["http://localhost:4200", "http://127.0.0.1:5500", "https://fullgeolocation.netlify.app", "https://fullgeoclone.netlify.app"],
        "methods": ["GET", "POST"],  # Métodos permitidos
        "allow_headers": ["Content-Type", "Authorization"]  # Cabeceras permitidas
    }
})
@app.route('/api/checkout', methods=['POST'])
def checkout():
    lookup_key = request.json.get('lookup_key')
    
    try:
        FULLGEO_DOMAIN = os.environ.get("DOMAIN")
        stripe.api_key = os.environ.get("SECRET_KEY")

        prices = stripe.Price.list(
            lookup_keys=[lookup_key],
            expand=['data.product']
        )

        session = stripe.checkout.Session.create(
            billing_address_collection='auto',
            payment_method_types=['card'],
            line_items=[{
                'price': prices['data'][0]['id'],
                'quantity': 1
            }],
            mode='subscription',
            success_url=f'{FULLGEO_DOMAIN}/success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{FULLGEO_DOMAIN}/cancel.html',
        )
        return jsonify(session), 200
    except Exception as e:
        return jsonify(error=str(e)), 400

@app.route('/api/create-user', methods=['POST'])
def create_user():
    try:
        data = CreateUserInput.model_validate(request.json)
        session_id = data.session_id

        stripe.api_key = os.environ.get("SECRET_KEY")
        session = stripe.checkout.Session.retrieve(session_id)
        # Extraer el correo electrónico del cliente desde la sesión
        customerId = session.get('customer')
        customer_email = session.get('customer_details', {}).get('email')
        customer_name = session.get('customer_details', {}).get('name')
        if customer_email:

            customer_email = customer_email.lower()
            SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
            SUPABASE_URL = os.environ.get("SUPABASE_URL")
            supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
            # Verificar si el usuario ya existe
            if user_exists_by_email(customer_email,supabase):
                response = CreateUserOut(codeUser="")  # Código 3 para usuario ya existente
                return jsonify(response.model_dump()), 409  # 409 Conflict
            
            timestamp = datetime.now()
            customer_password = generate_password()
            InsertUserRes = (supabase.table("users").insert({"email": customer_email, "password":customer_password,"verification_email": False , "suscripcion_id":customerId,"created_at": timestamp.isoformat()}).execute())
            InsertUserRes = json.loads(InsertUserRes.model_dump_json())
            userId = InsertUserRes['data'][0]['id']
            send_email(customer_name,customer_email,customer_password)            
            response = CreateUserOut(codeUser=userId)
            return jsonify(response.model_dump()), 200
        else:
            #Correo no disponible
            response = CreateUserOut(codeUser="")
            return jsonify(response.model_dump()), 404
    except Exception as e:
        response = CreateUserOut(codeUser="")
        return jsonify(response.model_dump()), 500


def user_exists_by_email(email, supabase:Client):
    # Realiza la consulta para verificar si el correo electrónico ya existe
    response = supabase.table("users").select("id").eq("email", email).execute()
    return len(response.data) > 0

def send_email(nam,mail,passw):
    htmlContent = build_template(nam,mail,passw)
    # Configuración del servidor SMTP
    smtp_server = "smtp.gmail.com"  # Servidor SMTP de Gmail
    smtp_port = 587  # Puerto para TLS
    smtp_user = "codsito27@gmail.com"  # Tu correo electrónico
    smtp_password = os.environ.get("PASSWORD_APLICATION") # Tu contraseña de aplicación (no la de tu correo)

    # Crear el mensaje
    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = mail  # Correo del destinatario
    msg['Subject'] = "Fullgeo Credenciales"

    # Adjuntar el contenido HTML
    msg.attach(MIMEText(htmlContent, 'html'))

    # Enviar el correo
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Habilitar TLS
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, msg['To'], msg.as_string())
        print("Correo enviado exitosamente.")
    except Exception as e:
        print(f"Error al enviar el correo: {e}")


def build_template(name,email,password):
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('emailtemplate.html')

    # Datos dinámicos
    datos = {
        "name": name,
        "email": email,
        "password":password
    }
    # Renderizar la plantilla con los datos
    html_content = template.render(datos)
    return html_content

def generate_password(longitud=8):
    # Definir los caracteres permitidos
    caracteres = string.ascii_letters + string.digits + string.punctuation
    
    # Generar la contraseña aleatoria
    contraseña = ''.join(random.choice(caracteres) for _ in range(longitud))
    
    return contraseña

@app.route('/api/phone-info', methods=['POST'])
def get_phone_info():
    response:PhoneNumberOut
    try:
        # Validamos los datos de entrada con Pydantic
        data = PhoneNumberInput.model_validate(request.json)
        code = data.code
        phone_number = data.phone_number
        code_lang = data.code_lang
        
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

        # Procesamos el número telefónico con phonenumbers
        parsed_number = phonenumbers.parse(f"{code}{phone_number}")
        
        # Obtenemos el país y operador
        country = geocoder.description_for_number(parsed_number, code_lang)  # País en inglés
        operator = carrier.name_for_number(parsed_number, code_lang)  # Operador en inglés
        # Modelo de salida
        response = PhoneNumberOut(status=True,description="Exitoso",country=country, operator=operator)
        return jsonify(response.model_dump()), 200
    except ValidationError as e:
        response = PhoneNumberOut(status=False,description=str(e),country="", operator="")
        return jsonify(response.model_dump()), 400
    except phonenumbers.phonenumberutil.NumberParseException as e:
        response = PhoneNumberOut(status=False,description=str(e),country="", operator="")
        return jsonify(response.model_dump()), 400
    except Exception as e:
        response = PhoneNumberOut(status=False,description=str(e),country="", operator="")
        return jsonify(response.model_dump()), 500
    



# @app.route('/api/account-verification',methods=['POST'])
# def account_verification():
#     response:AccountVerificationOut
#     try:
#         data = AccountVerificationInput.model_validate(request.json)
#         email = data.email

#         SUPABASE_URL = os.environ.get("SUPABASE_URL")
#         SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
#         timestamp = datetime.now()
#         supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
#         suscribeRes = (supabase.table("suscriptions").insert({"status": "", "created_at": timestamp.isoformat()}).execute())
#         suscribeRes = json.loads(suscribeRes.model_dump_json())
#         susId = suscribeRes['data'][0]['suscription_id']

#         suscribeRes = (supabase.table("suscriptions").insert({"status": "", "created_at": timestamp.isoformat()}).execute())
        
#         response_data = json.loads(dataResponse.model_dump_json())
        
#     except Exception as e:



@app.route('/api/send-sms', methods=['POST'])
def send_sms():
    response:SendSmsOut
    statusCode:int
    try:
        # Validamos los datos de entrada con Pydantic
        data = SendSmsInput.model_validate(request.json)
        code = data.code
        phone_number = data.phone_number
        uuid = data.uuid
        country = data.country
        
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
        timestamp = datetime.now()
        
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        dataResponse = (supabase.table("clients").select("uuid").eq("uuid",uuid).execute())
        response_data = json.loads(dataResponse.model_dump_json())
        if len(response_data['data']) != 0:
            API_KEY = os.environ.get("API_KEY")
            API_SECRET = os.environ.get("API_SECRET")
            BRAND_NAME = os.environ.get("BRAND_NAME")
            client = Vonage(Auth(api_key=API_KEY, api_secret=API_SECRET))
            
            # Procesamos el número telefónico con phonenumbers
            parsed_number:str = f"{code}{phone_number}"
            linkApp:str = f'https://fullgeolocation.netlify.app?uuid={uuid}'
            message = SmsMessage(
                to= parsed_number,
                from_=BRAND_NAME,
                text=f"Localiza tu telefono aquí: {linkApp} .",
                )
            response_sms: SmsResponse = client.sms.send(message)
            smsstatus:str
            if hasattr(response_sms, "messages") and len(response_sms.messages) > 0:
                # Acceder al primer mensaje en la lista
                message = response_sms.messages[0]
                if message.status == "0":
                    # Modelo de salida
                    smsstatus = "enviado"
                    statusCode = 200
                    response = SendSmsOut(status=True, description="Sms enviado correctamente")
                else:
                    smsstatus = "no enviado"
                    statusCode = 400
                    response = SendSmsOut(status=False, description="No se pudo enviar correctamente el mensaje")
            else:
                smsstatus = "error al enviar"
                statusCode = 500
                response = SendSmsOut(status=False, description="Ocurrió un error en el envio del mensaje")
            dataResponse = (supabase.table("locationrequests").insert({"status":"pendiente","smsstatus": smsstatus, "createdat": timestamp.isoformat(), "phonenumber": phone_number, "codecountry": code, "clientuuid": uuid, "country":country}).execute())
        else:
            statusCode = 500
            response = SendSmsOut(status=False, description="Cliente no existe")
        return jsonify(response.model_dump()), statusCode
    except ValidationError as e:
        statusCode = 400
        response = SendSmsOut(status=False, description=str(e))
        return jsonify(response.model_dump()), statusCode
    except Exception as e:
        statusCode = 500
        response = SendSmsOut(status=False, description=str(e))
        return jsonify(response.model_dump()), statusCode
    
@app.route('/api/save-location', methods=['POST'])
def save_location():
    response:SaveLocationOut
    statusCode:int
    try:
        data = SaveLocationInput.model_validate(request.json)
        user_uuid = data.user_uuid
        latitude = data.latitude
        longitude = data.longitude
        timestamp = data.timestamp
        country = data.city
        
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
            
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        dataResponse = (supabase.table("locationrequests").select("clientuuid").eq("clientuuid",user_uuid).execute())
        response_data = json.loads(dataResponse.model_dump_json())
        if len(response_data['data']) != 0:
            dataResponse = (supabase.table("locationrequests").update({"status": "localizado"}).eq({}).execute())
            dataResponse = (supabase.table("locations").insert({"clientuuid": user_uuid, "latitude": latitude, "longitude": longitude, "accuracy": "","city": country ,"capturedat": timestamp}).execute())
            statusCode = 201
            response = SaveLocationOut(code="00", description="Datos recibidos")
        else:
            statusCode = 404
            response = SaveLocationOut(code="01", description="Cliente no existe")
        return jsonify(response.model_dump()), statusCode
    except ValidationError as e:
        statusCode = 400
        response = SaveLocationOut(code="04", description=str(e))
        return jsonify(response.model_dump()), statusCode
    except Exception as e:
        statusCode = 500
        response = SaveLocationOut(code="04", description=str(e))
        return jsonify(response.model_dump()), statusCode

@app.route('/api/get-location', methods=['GET'])
def get_locations():
    try:
        return
    except ValidationError as e:
        statusCode = 400
        response = SaveLocationOut(code="04", description=str(e))
        return jsonify(response.model_dump()), statusCode
    except Exception as e:
        statusCode = 500
        response = SaveLocationOut(code="04", description=str(e))
        return jsonify(response.model_dump()), statusCode


if __name__ == '__main__':
    app.run(debug=True)