import os
import json
import uuid
import phonenumbers
import resend
from dotenv import load_dotenv
from flask import Flask, jsonify, json, make_response, request
from flask_cors import CORS
from phonenumbers import carrier, geocoder
from pydantic import ValidationError
from vonage import Auth, Vonage
from vonage_sms import SmsMessage, SmsResponse
from models import CreateUserInput, CreateUserOut, LocationResponse, LoginInput, LoginOut, PhoneNumberInput, PhoneNumberOut, ResetPsw, SendSmsInput, SendSmsOut, SaveLocationInput, SaveLocationOut, AccountVerificationInput, AccountVerificationOut, ChatBot, ChatBotOut, Unsubscribe, resResetPsw, resUnsubscribe
from datetime import datetime, timedelta
import smtplib
from flask_jwt_extended import (create_access_token, get_jwt_identity, jwt_required, JWTManager)
from google import genai
from google.genai import types
import stripe
from service import (
    create_user,
    unsubscribe_exists_by_email,
    insert_pending_order,
    mark_order_as_paid,
    exist_user,
    get_locations_request,
    insert_location_request,
    exist_location,
    update_credits,
    get_credits,
    insert_unsubscribe,
    user_exists_by_email,
    update_psw
)
import config
from db import get_client, supabase, refresh_if_needed

load_dotenv()


app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("SECRET_JWT")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=2)
jwt = JWTManager(app)

#Stripe
stripe.api_key = os.environ.get("SECRET_KEY")
#resend
resend.api_key =os.environ.get("RESEND_API_KEY")

client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))


# Habilitar CORS para todas las rutas
# Configuración de CORS
CORS(app, origins=["http://localhost:4200", "http://127.0.0.1:5000"], 
     allow_methods=["GET", "POST","OPTIONS"],
     allow_headers= ["Content-Type", "Authorization", "x-api-key"],
     allow_credentials=True,
     supports_credentials=True)


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("stripe-signature")

    print("🔔 Webhook recibido")
    try:
        # ✅ Verifica la firma del webhook
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.environ.get("WEBHOOK_SECRET")
        )
    except ValueError as e:
        print("❌ Error en el cuerpo del evento:", e)
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.SignatureVerificationError as e:
        print("❌ Error de firma:", e)
        return jsonify({"error": "Invalid signature"}), 400

    # 🎯 Procesar evento
    if event["type"] == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]
        payment_id = payment_intent["id"]
        customer_id = payment_intent.get("customer")

        print(f"✅ Pago exitoso: {payment_id} para el cliente {customer_id}")

        # 🔑 Crear suscripción automáticamente tras el pago exitoso
        try:
            price_id = os.environ.get("PRICE_ID")
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                trial_period_days=1,
                expand=["latest_invoice.payment_intent"]
            )

            print(f"📦 Suscripción creada: {subscription.id}")
            jwt_token = refresh_if_needed()
            order = mark_order_as_paid(payment_id,jwt_token)
            name = order["name"]
            email = order["email"]
            # (Opcional) Actualizar tu base de datos o lógica interna
            create_user(name, email, jwt_token)
        except Exception as e:
            print("❌ Error al crear la suscripción o usuario:", e)
            return jsonify({"error": str(e)}), 400
    return jsonify({"success": True}), 200

@app.route('/api/checkout', methods=['POST'])
def checkout():
    payment_method_id = request.json.get("paymentMethodId")
    name = request.json.get("name")
    email = request.json.get("email")

    try:
        # 🧾 Crear cliente
        customer = stripe.Customer.create(
            name=name,
            email=email,
            payment_method=payment_method_id,
            invoice_settings={"default_payment_method": payment_method_id},
        )

        # 💳 Crear PaymentIntent (solo se confirma en frontend)
        payment_intent = stripe.PaymentIntent.create(
            amount=50,  # 💰 Pago inicial (por ejemplo, verificación)
            currency="eur",
            customer=customer.id,
            payment_method=payment_method_id,
            confirmation_method="automatic",
        )

        jwt_token = refresh_if_needed()
        # Guardar pedido pendiente en tu BD
        insert_pending_order(name, email, 'es', payment_intent.id, jwt_token)

        # 🔄 Ya no se crea la suscripción aquí — se hace en el webhook
        return jsonify({
            "clientSecret": payment_intent.client_secret,
            "customerId": customer.id
        }), 200

    except Exception as e:
        print("❌ Error en checkout:", e)
        return jsonify(error=str(e)), 400

@app.route('/api/phone-info', methods=['POST'])
def get_phone_info():
    response:PhoneNumberOut
    api_key = request.headers.get("X-API-KEY")
    API_SECRET = os.environ.get("SECRET_API")

    if api_key != API_SECRET:
        return jsonify({"error": "No autorizado"}), 403

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

# @app.route('/api/get-location', methods=['GET'])
# def get_locations():
#     try:
#         return
#     except ValidationError as e:
#         statusCode = 400
#         response = SaveLocationOut(code="04", description=str(e))
#         return jsonify(response.model_dump()), statusCode
#     except Exception as e:
#         statusCode = 500
#         response = SaveLocationOut(code="04", description=str(e))
#         return jsonify(response.model_dump()), statusCode

@app.route("/api/login", methods=["POST"])
def login():
    data = LoginInput.model_validate(request.json)
    email = data.email
    password = data.password

    jwt_token = refresh_if_needed()
    userData = exist_user(jwt_token,email.lower(),password)
    if len(userData.data)<=0:
            response = LoginOut(message='Unauthorized',token='')
            return jsonify(response.model_dump()), 401
    
    userData = json.loads(userData.model_dump_json())
    userId = userData['data'][0]['id']
    access_token = create_access_token(identity=str(userId))
    response = LoginOut(message="Success", token=access_token)
    return jsonify(response.model_dump()), 200

@app.route("/api/unsubscribe", methods=["POST"])
def unsubscribe():
    api_key = request.headers.get("X-API-KEY")
    API_SECRET = os.environ.get("SECRET_API")
    if api_key != API_SECRET:
        return jsonify({"error": "No autorizado"}), 403
    data = Unsubscribe.model_validate(request.json)
    email = data.email
    jwt_token = refresh_if_needed()
    client_supabase = get_client(jwt_token)
    statuscode =200
    try:
        if user_exists_by_email(client_supabase,email):
            if unsubscribe_exists_by_email(client_supabase,email):
                statuscode=404
                response = resUnsubscribe(message="Email no cuenta con subscripción activa")
            else:
                statuscode=200
                insert_unsubscribe(jwt_token,email.lower())
                response = resUnsubscribe(message="Suscripcion eliminada con exito")   
        else:
            statuscode=404
            response = resUnsubscribe(message="Email no cuenta con subscripción activa")
        return jsonify(response.model_dump()), statuscode
    except Exception as e:
        print(f"[unsubscribe]: {e}")
        statuscode=500
        response = resUnsubscribe(message="Ocurrió un error")
        return jsonify(response.model_dump()), statuscode

@app.route("/api/reset-psw", methods=["POST"])
def reset_psw():
    api_key = request.headers.get("X-API-KEY")
    API_SECRET = os.environ.get("SECRET_API")

    # Validar API Key
    if api_key != API_SECRET:
        return jsonify({"error": "No autorizado"}), 403

    try:
        # Validar datos de entrada
        data = ResetPsw.model_validate(request.json)
        email = data.email

        # Obtener token y cliente
        jwt_token = refresh_if_needed()
        client_supabase = get_client(jwt_token)

        # Valor por defecto
        statuscode = 200
        response = resResetPsw(message="Contraseña restablecida correctamente")

        # Lógica principal
        if user_exists_by_email(client_supabase, email):
            update_psw(client_supabase, email)
        else:
            statuscode = 404
            response = resResetPsw(message="Usuario no encontrado")

        return jsonify(response.model_dump()), statuscode

    except ValidationError as e:
        print(f"[reset-psw] Error de validación: {e}")
        response = resResetPsw(message=str(e))
        return jsonify(response.model_dump()), 400

    except Exception as e:
        print(f"[reset-psw] Error interno: {e}")
        response = resResetPsw(message="Ocurrió un error interno")
        return jsonify(response.model_dump()), 500

@app.route('/api/send-sms', methods=['POST'])
@jwt_required(locations=["headers"])
def send_sms():
    id_user = get_jwt_identity()
    jwt_token = refresh_if_needed()

    try:
        # Validar entrada con Pydantic
        data = SendSmsInput.model_validate(request.json)
        credits = data.credits

        # Si no hay créditos suficientes
        if credits <= 0:
            response = SendSmsOut(status=False, description="No tienes créditos suficientes")
            return jsonify(response.model_dump()), 400

        # Configuración de entorno
        API_KEY = os.environ.get("API_KEY")
        API_SECRET = os.environ.get("API_SECRET")
        BRAND_NAME = os.environ.get("BRAND_NAME")
        DOMAIN_LOCALIZE = os.environ.get("DOMAIN_LOCALIZATION")

        # Inicializar cliente SMS
        client = Vonage(Auth(api_key=API_KEY, api_secret=API_SECRET))

        # Preparar datos
        message_uuid = str(uuid.uuid4())
        code_number = data.code.replace("+", "")
        parsed_number = f"{code_number}{data.phone_number}"
        linkApp = f"{DOMAIN_LOCALIZE}?uuid={message_uuid}"

        # Crear mensaje
        message = SmsMessage(
            to=parsed_number,
            from_=BRAND_NAME or ".",
            text=f"Localiza tu teléfono aquí: {linkApp}"
        )

        # Enviar SMS
        response_sms: SmsResponse = client.sms.send(message)

        # Analizar respuesta
        smsstatus = 2
        statusCode = 500
        description = "Ocurrió un error en el envío del mensaje"

        if hasattr(response_sms, "messages") and len(response_sms.messages) > 0:
            msg = response_sms.messages[0]
            if msg.status == "0":
                smsstatus = 1
                statusCode = 200
                description = "SMS enviado correctamente"
            else:
                smsstatus = 0
                statusCode = 400
                description = f"No se pudo enviar el mensaje: {msg.error_text}"

        # Guardar registro del intento
        timestamp = datetime.now().isoformat()
        insert_location_request(jwt_token, message_uuid, smsstatus, timestamp, data.code, data.phone_number, data.code_country, id_user)

        # Actualizar créditos si fue exitoso
        if smsstatus == 1:
            update_credits(jwt_token, credits - 1, int(id_user))

        # Respuesta final
        response = SendSmsOut(status=(smsstatus == 1), description=description)
        return jsonify(response.model_dump()), statusCode

    except ValidationError as e:
        print(f"[api/send-sms] Validation Error: {e}")
        response = SendSmsOut(status=False, description=str(e))
        return jsonify(response.model_dump()), 400

    except Exception as e:
        print(f"[api/send-sms] Unexpected Error: {e}")
        response = SendSmsOut(status=False, description=str(e))
        return jsonify(response.model_dump()), 500

@app.route('/api/save-location', methods=['POST'])
def save_location():
     statusCode:int
     try:
         data = SaveLocationInput.model_validate(request.json)
         message_uuid = data.message_uuid
         latitude = data.latitude
         longitude = data.longitude
         timestamp = data.timestamp
         country = data.city
       
         rldata_response = (supabase.table("LocationRequests").update({"status": True}).eq("message_uuid",message_uuid).execute())
         rldata_response = json.loads(rldata_response.model_dump_json())
         if len(rldata_response['data']) != 0:
             if exist_location(message_uuid):
                 locationUp = (supabase.table("Locations").update({"latitude": latitude, "longitude": longitude, "city": country ,"captured_at": timestamp}).eq('location_message_uuid',message_uuid).execute())
             else:
                 location = (supabase.table("Locations").insert({"location_message_uuid": message_uuid, "latitude": latitude, "longitude": longitude, "city": country ,"captured_at": timestamp}).execute())
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
        jwt_token = refresh_if_needed()
        location_requests = get_locations_request(id_user, jwt_token)
        credits=get_credits(jwt_token,id_user)
        location_requests = json.loads(location_requests.model_dump_json())
        return jsonify(details={"credits":credits,"history":location_requests['data']}), 200
    except Exception as e:
        return jsonify(details={}), 500

@app.route("/api/chat", methods=["POST"])
def chat():
    statusCode:int
    api_key = request.headers.get("X-API-KEY")
    API_SECRET = os.environ.get("SECRET_API")

    # Validar API Key
    if api_key != API_SECRET:
        return jsonify({"error": "No autorizado"}), 403
    
    data = ChatBot.model_validate(request.json)
    user_message = data.message
    try:
        response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    config=types.GenerateContentConfig(
                        system_instruction="""
                                    Eres un asistente virtual de la Web QuickGeo.

                                    Tu función es ayudar a los usuarios respondiendo sobre:
                                    - Información general sobre QuickGeo
                                    - Horarios de atención (lunes a viernes de 9:00 a 18:00).
                                    - Disponibilidad de servicios (24/7)
                                    - Precios de nuestros planes (0.50€/prueba 24hrs luego 50€/mes).
                                    - Métodos de contacto oficiales (contact@quickgeo.mobi).
                                    - Funciones principales de nuestra App QuickGeo y cómo utilizarlas.

                                    Las caracteristicas de QuickGeo son las siguientes:

                                    - Soporte Universal: Accede desde cualquier dispositivo sin importar la marca o el sistema que uses, la plataforma se adapta para ofrecerte la mejor experiencia.
                                    - Localización precisa: Encuentra cualquier número con exactitud en segundos desde cualquier lugar. Funciona con todas las redes móviles sin importar la operadora.
                                    - No se requiere instalación: Usa el servicio al instante sin descargar nada ni configurar tu dispositivo. Solo ingresa el número y obtén la información al momento
                                    - Privacidad garantizada: Tu seguridad es nuestra prioridad navegás de forma completamente anónima sin rastreos para que disfrutes del servicio con total confianza.

                                    Como funciona:

                                    - Realizar una búsqueda en un número: Nuestra tecnología comienza a localizar e identificar el teléfono asociado.
                                    - Solicitar una ubicación precisa: Enviamos un mensaje de texto al teléfono objetivo para localizarlo. Este mensaje es anónimo por defecto, pero puede ser personalizado para aumentar las posibilidades de éxito.
                                    - Obtén tus resultados: Serás informado automáticamente con la dirección tan pronto como el destinatario confirme su ubicación.

                                    Siempre debes mantener un tono cordial, profesional y enfocado en resolver las necesidades del cliente. 
                                    Si alguna información solicitada no está disponible, invítalos amablemente a comunicarse directamente a través de nuestros canales oficiales.
                                    Recuerda: No inventes información. Si no sabes la respuesta exacta, deriva al contacto oficial.
                                    """),
                    contents=user_message
                )
        response = ChatBotOut(response=response.text)
        return jsonify(response.model_dump()), 200
    except ValidationError as e:
        statusCode = 400
        response = ChatBotOut(response=str(e))
        return jsonify(response.model_dump()), statusCode
    except Exception as e:
        statusCode = 500
        response = ChatBotOut(response=str(e))
        return jsonify(response.model_dump()), statusCode


if __name__ == '__main__':
    app.run(debug=True)