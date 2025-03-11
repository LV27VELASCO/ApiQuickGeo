import os
import json
import random
import string
import uuid
import phonenumbers
from dotenv import load_dotenv
from flask import Flask, jsonify, json, make_response, request
from flask_cors import CORS
from phonenumbers import carrier, geocoder
from pydantic import ValidationError
from vonage import Auth, Vonage
from vonage_sms import SmsMessage, SmsResponse
from jinja2 import Environment, FileSystemLoader
from models import CreateUserInput, CreateUserOut, LocationResponse, LoginInput, LoginOut, PhoneNumberInput, PhoneNumberOut, SendSmsInput, SendSmsOut, SaveLocationInput, SaveLocationOut, AccountVerificationInput, AccountVerificationOut
from supabase import create_client, Client
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask_jwt_extended import (create_access_token, get_jwt_identity, jwt_required, JWTManager)

import stripe

load_dotenv()


app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("SECRET_JWT")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=2)
jwt = JWTManager(app)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
            
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# Habilitar CORS para todas las rutas
# Configuración de CORS
CORS(app, origins=["http://localhost:4200", "http://127.0.0.1:5500", "https://fullgeolocation.netlify.app", "https://fullgeoclone.netlify.app"], 
     supports_credentials=True, 
     allow_headers=["Content-Type", "Authorization"], 
     methods=["GET", "POST", "OPTIONS"])

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
            cancel_url=f'{FULLGEO_DOMAIN}/',
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
            # Verificar si el usuario ya existe
            if user_exists_by_email(customer_email):
                (supabase.table("users").update({"suscripcion_id": customerId}).eq("email",customer_email).execute())
                response = CreateUserOut(status=False)  # Código 3 para usuario ya existente
                return jsonify(response.model_dump()), 409  # 409 Conflict

            timestamp = datetime.now()
            customer_password = generate_password()
            InsertUserRes = (supabase.table("users").insert({"email": customer_email, "password":customer_password,"verification_email": False , "suscripcion_id":customerId,"created_at": timestamp.isoformat()}).execute())
            InsertUserRes = json.loads(InsertUserRes.model_dump_json())
            userId = InsertUserRes['data'][0]['id']
            send_email(customer_name,customer_email,customer_password)            
            response = CreateUserOut(status=True)
            return jsonify(response.model_dump()), 200
        else:
            #Correo no disponible
            response = CreateUserOut(status=False)
            return jsonify(response.model_dump()), 404
    except Exception as e:
        response = CreateUserOut(status=False)
        return jsonify(response.model_dump()), 500

@app.route('/api/phone-info', methods=['POST'])
def get_phone_info():
    response:PhoneNumberOut
    try:
        # Validamos los datos de entrada con Pydantic
        data = PhoneNumberInput.model_validate(request.json)
        code = data.code
        phone_number = data.phone_number
        code_lang = data.code_lang

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

@app.route("/api/login", methods=["POST"])
def login():
    data = LoginInput.model_validate(request.json)
    email = data.email
    password = data.password

    userData = exist_user(email,password)
    if len(userData.data)<=0:
            response = LoginOut(message='Unauthorized',token='')
            return jsonify(response.model_dump()), 401
    
    userData = json.loads(userData.model_dump_json())
    userId = userData['data'][0]['id']
    access_token = create_access_token(identity=userId)
    response = LoginOut(message="Success", token=access_token)
    return jsonify(response.model_dump()), 200

@app.route('/api/send-sms', methods=['POST'])
@jwt_required(locations=["headers"])
def send_sms():
    statusCode:int
    id_user = get_jwt_identity()
    try:
        # Validamos los datos de entrada con Pydantic
        data = SendSmsInput.model_validate(request.json)
        code = data.code
        phone_number = data.phone_number

        API_KEY = os.environ.get("API_KEY")
        API_SECRET = os.environ.get("API_SECRET")
        BRAND_NAME = os.environ.get("BRAND_NAME")
        rl_uuid = uuid.uuid4()
        client = Vonage(Auth(api_key=API_KEY, api_secret=API_SECRET))
            
            # Procesamos el número telefónico con phonenumbers
        parsed_number:str = f"{code}{phone_number}"
        linkApp:str = f'https://fullgeolocation.netlify.app?uuid={rl_uuid}'
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
                smsstatus = 1
                statusCode = 200
                response = SendSmsOut(status=True, description="Sms enviado correctamente")
            else:
                smsstatus = 0
                statusCode = 400
                response = SendSmsOut(status=False, description="No se pudo enviar correctamente el mensaje")
        else:
            smsstatus = 2
            statusCode = 500
            response = SendSmsOut(status=False, description="Ocurrió un error en el envio del mensaje")
        
        timestamp = datetime.now()
        dataResponse = (supabase.table("locationrequests").insert({"requestid":str(rl_uuid),"status":False,"smsstatus": smsstatus, "createdat": timestamp.isoformat(),"codephone":code,"phonenumber": phone_number, "codecountry": code, "useruuid": id_user}).execute())
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
    statusCode:int
    try:
        data = SaveLocationInput.model_validate(request.json)
        rl_uuid = data.rl_uuid
        latitude = data.latitude
        longitude = data.longitude
        timestamp = data.timestamp
        country = data.city
        
        rldata_response = (supabase.table("locationrequests").update({"status": True}).eq("requestid",rl_uuid).execute())
        rldata_response = json.loads(rldata_response.model_dump_json())
        if len(rldata_response['data']) != 0:
            if exist_location(rl_uuid):
                locationUp = (supabase.table("locations").update({"latitude": latitude, "longitude": longitude, "city": country ,"capturedat": timestamp}).eq('location_request_uuid',rl_uuid).execute())
            else:
                location = (supabase.table("locations").insert({"location_request_uuid": rl_uuid, "latitude": latitude, "longitude": longitude, "city": country ,"capturedat": timestamp}).execute())
            statusCode = 201
            response = SaveLocationOut(message="Success")
        else:
            statusCode = 404
            response = SaveLocationOut(message="Bad Request location")
        return jsonify(response.model_dump()), statusCode
    except ValidationError as e:
        statusCode = 400
        response = SaveLocationOut(message=str(e))
        return jsonify(response.model_dump()), statusCode
    except Exception as e:
        statusCode = 500
        response = SaveLocationOut(message=str(e))
        return jsonify(response.model_dump()), statusCode

@app.route("/api/location-requests", methods=["GET"])
@jwt_required(locations=["headers"])  # Ahora busca el token en el encabezado
def location_requests():
    try:
        id_user = get_jwt_identity()
        # First get the location requests for this user
        location_requests =  supabase.table("locationrequests").select("status, smsstatus, codephone, phonenumber, codecountry, createdat, " + "locations(latitude, longitude, capturedat, city)").eq("useruuid", id_user).order("createdat", desc=True).execute()
        location_requests = json.loads(location_requests.model_dump_json())
        return jsonify(details=location_requests['data']), 200
    except Exception as e:
        return jsonify(details=[]), 500

def exist_user(email, password):
    # Realiza la consulta para verificar si el correo electrónico ya existe
    response = supabase.table("users").select("id").eq("email", email).eq("password",password).execute()
    return response

def user_exists_by_email(email):
    # Realiza la consulta para verificar si el correo electrónico ya existe
    response = supabase.table("users").select("id").eq("email", email).execute()
    return len(response.data) > 0

def send_email(nam,mail,passw):
    htmlContent = build_template(nam,mail,passw)
    # Configuración del servidor SMTP
    smtp_server = os.environ.get("SMTP_SERVER")  # Servidor SMTP de Gmail
    smtp_port = 587  # Puerto para TLS
    smtp_user = os.environ.get("SMTP_USER")
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

def generate_password(longitud=9):
    # Definir los caracteres permitidos
    caracteres = string.ascii_letters + string.digits + " $_()#!?*"
    # Generar la contraseña aleatoria
    contraseña = ''.join(random.choice(caracteres) for _ in range(longitud))
    return contraseña

def exist_location(rl_uuid):
    # Realiza la consulta para verificar si ya hay registrada una ubicacion
    response = supabase.table("locations").select("locationuuid").eq("location_request_uuid", rl_uuid).execute()
    return len(response.data) > 0


if __name__ == '__main__':
    app.run(debug=True)