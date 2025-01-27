from pydantic import BaseModel
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
    uuid:str

# Modelo de entrada send-sms
class SendSmsInput(BaseModel):
    code:str
    phone_number: str
    country: str
    uuid:str

# Modelo de salida send-sms
class SendSmsOut(BaseModel):
    status:bool
    description: str
    
# Modelo de salida send-sms
class SaveLocationInput(BaseModel):
    user_uuid:str
    latitude: float
    longitude:float
    timestamp: str
    
class SaveLocationOut(BaseModel):
    code:str
    description: str