from datetime import datetime
import json
import os
from typing import Optional
from jinja2 import Environment, FileSystemLoader
import resend
from db import supabase, get_client
import config


templates = {
    "en": "emailtemplate_en.html",
    "es": "emailtemplate_es.html",
    "fr": "emailtemplate_fr.html",
    "pt": "emailtemplate_pt.html",
    "de": "emailtemplate_de.html"
}

#Crea un usuario nuevo o actualiza si ya existe (webhook).
#Retorna un diccionario con {status: bool, code: int, message: str}.
def create_user(customer_name, customer_email, jwt_token):
    client_supabase = get_client(jwt_token)
    user_uuid = client_supabase.auth.get_user().user.id

    try:
        # Validar parámetros
        if not customer_email:
            return {"status": False, "code": 404, "message": "Correo no disponible"}

        # Normalizar el email
        customer_email = customer_email.lower()
        customer_password = generate_password()

        # Verificar si el usuario ya existe
        if user_exists_by_email(client_supabase, customer_email):
            update_client(client_supabase, customer_email, customer_password)
            # Enviar correo de confirmación
            send_email(customer_name, customer_email, customer_password)
            return {"status": True, "code": 200, "message": "Usuario ya existente, password actualizada"}

        # Crear usuario nuevo
        insert_res = insert_client(client_supabase,customer_name,customer_email, customer_password, user_uuid)
       
        # Enviar correo de confirmación
        send_email(customer_name, customer_email, customer_password)

        return {"status": True, "code": 200, "message": "Usuario creado exitosamente"}
    except Exception as e:
        print(f"[create_user] Error: {e}")
        return {"status": False, "code": 500, "message": "Error interno del servidor"}

#Inserta el usuario nuevo en la BD.
def insert_client(client_supabase, name:str, email: str, password: str, user_uuid: str) -> Optional[int]:
    timestamp = datetime.now()
    insert_res = client_supabase.table("Users").insert({
            "name": name,
            "email": email,
            "password": password,
            "verification_email": False,
            "created_at": timestamp.isoformat(),
            "user_uuid": user_uuid
        }).execute()
    return insert_res.data[0]['id'] if insert_res.data else None

#Actualiza el usuario nuevo en la BD.
def update_client(client_supabase, email: str, password: str) -> Optional[int]:
    timestamp = datetime.now()
    update_res = client_supabase.table("Users").update({"password": password}).eq("email", email).execute()
    return update_res.data[0]['id'] if update_res.data else None

#Envia el email.
def send_email(name: str, email: str, password: str, lang: str='es'):
    htmlContent = build_template(name, email, password, lang)
    try:
        # Preparar parámetros para Resend
        params: resend.Emails.SendParams = {
            "from": f"{os.environ.get('FROM_NAME')} <{os.environ.get('FROM_EMAIL')}>",
            "to": [email],
            "subject": os.environ.get("SUBJECT_MAIL"),
            "html": htmlContent,
        }

        # Enviar email
        email_response = resend.Emails.send(params)
        print("Correo enviado")

    except Exception as e:
       print(f"[send_email] Error: {e}")

#Inserta ordenes pendientes en BD (checkout)
def insert_pending_order(name:str, email:str, locale:str, payment_id:str, jwt_token:str):
    client_supabase = get_client(jwt_token)
    user_uuid = client_supabase.auth.get_user().user.id
    client_supabase.table("Pending_orders") \
            .insert({
                "name": name,
                "locale":locale,
                "email": email,
                "payment_intent": payment_id,
                "user_uuid": user_uuid
            }).execute()

#Actualiza ordenes pendientes en BD (webhook)
def mark_order_as_paid(payment_id:str, jwt_token:str):
    client_supabase = get_client(jwt_token)
    user_id = client_supabase.auth.get_user().user.id
    response_base = client_supabase.table("Pending_orders").select("*").eq("payment_intent",payment_id).execute()

    if len(response_base.data) > 0:
        # ✅ actualizar
        order = response_base.data[0]
        order_id = response_base.data[0]["id"]
        client_supabase.table("Pending_orders") \
            .update({"success": True}) \
            .eq("id", order_id) \
            .execute()
        print(f"[INFO] Orden {order_id} marcada como pagada.")
        return order
    else:
        print(f"[WARN] No se encontró ninguna orden pendiente con payment_intent={payment_id}")
        return None

def user_exists_by_email(client_supabase, email):
    # Realiza la consulta para verificar si el correo electrónico ya existe
    response = client_supabase.table("Users").select("id").eq("email", email).limit(1).execute()
    return response.data[0] if response.data else None

def exist_user(jwt_token, email, password):
    # Realiza la consulta para verificar si el correo electrónico ya existe
    client_supabase = get_client(jwt_token)
    response = client_supabase.table("Users").select("id").eq("email", email).eq("password",password).execute()
    return response

def get_locations_request(id_user, jwt_token:str):
    # First get the location requests for this user
    try:
        client_supabase = get_client(jwt_token)
        location_requests =  client_supabase.table("LocationRequests").select("status, smsstatus, codephone, phonenumber, codecountry, created_at, " + "Locations(latitude, longitude, captured_at, city)").eq("user_id", id_user).order("created_at", desc=True).execute()
        return location_requests
    except Exception as e:
        print(f"[getLocationsRequest] Error: {e}")

def insert_location_request(jwt_token, message_uuid, smsstatus, created_at, code, phone_number, code_country, id_user):
    # First get the location requests for this user
    try:
        client_supabase = get_client(jwt_token)
        location_requests =  client_supabase.table("LocationRequests").insert({"message_uuid":str(message_uuid), "status":False,"smsstatus": smsstatus, "created_at": created_at,"codephone":code,"phonenumber": phone_number, "codecountry": code_country, "user_id": id_user}).execute()
        return location_requests
    except Exception as e:
        print(f"[insertLocationRequest] Error: {e}")

def insert_unsubscribe(jwt_token, email):
    # First get the location requests for this user
    try:
        client_supabase = get_client(jwt_token)
        user_uuid = client_supabase.auth.get_user().user.id
        unsubscribe =  client_supabase.table("Unsubscribe").insert({"email":email,"user_uuid":user_uuid}).execute()
        return unsubscribe
    except Exception as e:
        print(f"[insertUnsubscribe] Error: {e}")

def unsubscribe_exists_by_email(client_supabase, email):
    # First get the location requests for this user
    try:
        unsubscribe =  client_supabase.table("Unsubscribe").select({"email":email}).execute()
        return unsubscribe.data[0] if unsubscribe.data else None
    except Exception as e:
        print(f"[existUnsubscribe] Error: {e}")

def update_credits(jwt_token, credits: int, id_user:int) -> Optional[int]:
    client_supabase = get_client(jwt_token)
    update_res = client_supabase.table("Users").update({"credits": credits}).eq("id", id_user).execute()
    return update_res.data[0]['id'] if update_res.data else None

def get_credits(jwt_token, id_user:int) -> Optional[int]:
    client_supabase = get_client(jwt_token)
    update_res = client_supabase.table("Users").select("credits").eq("id", id_user).execute()
    return update_res.data[0]['credits'] if update_res.data else None

def build_template(name: str, email: str, password: str, lang:str) -> str:
    env = Environment(loader=FileSystemLoader('templates'))

    template_name = templates.get(lang.lower(), "emailtemplate_es.html")
    template = env.get_template(template_name)
    return template.render({"name": name, "email": email, "password": password})

def exist_location(message_uuid):
    # Realiza la consulta para verificar si ya hay registrada una ubicacion
    response = supabase.table("Locations").select("id").eq("location_request_id", message_uuid).execute()
    return len(response.data) > 0

def generate_password(length: int = 12) -> str:
    """Genera una contraseña aleatoria segura."""
    import random, string
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

#Actualiza el usuario nuevo en la BD.
def update_psw(client_supabase, email: str) -> Optional[int]:
    customer_password = generate_password()
    update_res = client_supabase.table("Users").update({"password": customer_password}).eq("email", email).execute()
    # Enviar correo de confirmación
    customer_name = update_res.data[0]['name'].lower()
    send_email(customer_name, email, customer_password)

def update_locations(client_supabase, message_uuid, latitude,longitude, country, timestamp) -> Optional[int]:
    if exist_location(message_uuid):
        locationUp = client_supabase.table("Locations").update({"latitude": latitude, "longitude": longitude, "city": country ,"captured_at": timestamp}).eq('location_message_uuid',message_uuid).execute()
    else:
        location = client_supabase.table("Locations").insert({"location_message_uuid": message_uuid, "latitude": latitude, "longitude": longitude, "city": country ,"captured_at": timestamp}).execute()
             


