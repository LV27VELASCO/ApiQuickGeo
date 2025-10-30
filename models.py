from pydantic import BaseModel
from typing import List
# Modelo de entrada phone-info
class PhoneNumberInput(BaseModel):
    code:str
    phone_number: str
    code_lang: str

# Modelo de salida phone-info
class PhoneNumberOut(BaseModel):
    status:bool
    description: str
    country: str
    operator: str

# Modelo de entrada send-sms
class SendSmsInput(BaseModel):
    code:str
    phone_number: str
    code_country:str
    message:str
    credits:int

# Modelo de salida send-sms
class SendSmsOut(BaseModel):
    status:bool
    description: str
    
# Modelo de salida send-sms
class SaveLocationInput(BaseModel):
    message_uuid:str
    latitude: float
    longitude:float
    timestamp: str  
    city:str
    
class SaveLocationOut(BaseModel):
    message:str

class AccountVerificationInput(BaseModel):
    email:str

class AccountVerificationOut(BaseModel):
    codigo:str
    descripcion:str

class CreateUserInput(BaseModel):
    session_id:str

class CreateUserOut(BaseModel):
    status:bool = False

class LoginInput(BaseModel):
    email:str
    password:str

class LoginOut(BaseModel):
    message:str
    token:str

class Location(BaseModel):
    latitude:float
    longitude:float
    capturedAt:str
    city:str

class LocationResponse(BaseModel):
    status:bool
    smsStatus:int
    phoneNumber:str
    codeCountry:str
    createAt:str
    location:List[Location]

class ChatBot(BaseModel):
    message:str

class ChatBotOut(BaseModel):
    response:str

class Unsubscribe(BaseModel):
    email:str

class resUnsubscribe(BaseModel):
    message:str

class ResetPsw(BaseModel):
    email:str

class resResetPsw(BaseModel):
    message:str