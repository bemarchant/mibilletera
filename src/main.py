import re
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import gspread
import os
from datetime import datetime, timedelta

# Configuración de los scopes de acceso
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/spreadsheets']

def authenticate_gmail():
    """Autentica al usuario con OAuth 2.0 y devuelve un servicio de Gmail."""
    creds = None
    # Carga las credenciales desde el archivo
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:  # Si las credenciales no son válidas
        if creds and creds.expired and creds.refresh_token:  # Si el token expiró y hay un refresh_token disponible
            creds.refresh(Request())  # Renueva el token automáticamente
        else:
            # Si no hay credenciales válidas, inicia el flujo de autorización
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=8080)
        # Guarda las credenciales renovadas o nuevas
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def connect_gsheet(sheet_url):
    """Conecta con Google Sheets y devuelve el objeto de la hoja."""
    gc = gspread.service_account(filename='mibilletera-448919-5970eb938a1a.json')
    sheet = gc.open_by_url(sheet_url)
    return sheet

def get_shops(sheet):
    """Lee la pestaña 'tiendas' y genera un diccionario con categorías."""
    tiendas_worksheet = sheet.worksheet('tiendas')
    tiendas_data = tiendas_worksheet.get_all_records()
    tiendas_dict = {tienda['código']: {'category' : tienda['categoría'], 'name' : tienda['nombre']} for tienda in tiendas_data if tienda['categoría']}
    return tiendas_dict

def write_expensive(sheet, shop, date, time, total, category):
    """Escribe un gasto en la pestaña 'gastos'."""
    gastos_worksheet = sheet.worksheet('gastos')
    date_str = date.strftime('%Y-%m-%d')
    time_str = time.strftime('%H:%M:%S')
    gastos_worksheet.append_row([shop, date_str, time_str, total, category])

def extract_transaction_details(body):
    """Extrae la tienda, el monto y la fecha/hora del mensaje."""
    # Extrae la tienda usando una expresión regular
    shop_match = re.search(r'en (.*?) el', body)
    shop = shop_match.group(1) if shop_match else None

    # Extrae la fecha y hora usando una expresión regular
    datetime_match = re.search(r'el (\d{2}/\d{2}/\d{4} \d{2}:\d{2})', body)
    expensive_datetime_str = datetime_match.group(1) if datetime_match else None

    # Extrae el monto
    expensive_total_match = re.search(r'compra por \$(\d+(?:\.\d{3})*)', body)
    expensive_total = expensive_total_match.group(1).replace('.', '') if expensive_total_match else None

    return shop, expensive_datetime_str, expensive_total

def find_emails(service, sender, date):
    """Busca correos en Gmail por remitente y retorna una lista de mensajes."""
    next_day = (date + timedelta(days=1)).strftime('%Y/%m/%d')
    date = date.strftime('%Y/%m/%d')

    query = f'from:{sender} after:{date} before:{next_day}'
    results = service.users().messages().list(userId='me', q=query).execute()
    messages = results.get('messages', [])
    emails = []

    for message in messages:
        msg = service.users().messages().get(userId='me', id=message['id']).execute()
        payload = msg['payload']
        headers = payload['headers']

        # Obtiene el asunto
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), None)
        
        body = ""
        # Obtiene el cuerpo del mensaje
        if subject == 'Cargo en Cuenta':
            body = msg['snippet']
        
            # Extrae detalles si el cuerpo está presente
            if body:
                expensive_shop, expensive_datetime_str, expensive_total = extract_transaction_details(body)
                emails.append({'subject': subject,
                                'body': body,
                                'expensive_shop': expensive_shop,
                                'expensive_datetime_str': expensive_datetime_str,
                                'expensive_total': expensive_total})
        else:
            continue
    
    return emails

def lambda_handler(event, context):
    # Autentica y conecta al servicio de Gmail
    service = authenticate_gmail()
    
    # Conecta con Google Sheets
    sheet_url = "https://docs.google.com/spreadsheets/d/1b2wIC_QHZ8NI5-C1hNH6kTDvpAfxZ-o_Cdh3_7B8SyE/edit#gid=2100903900"
    sheet = connect_gsheet(sheet_url)

    # Lee las categorías desde la pestaña 'tiendas'
    shops_dict = get_shops(sheet)
    
    print(f"shops : {shops_dict}")
    # Especifica el remitente a buscar
    remitente = "enviodigital@bancochile.cl"
    
    # Procesa correos
    emails = []

    date = datetime.now() - timedelta(days=1)
    
    emails.extend(find_emails(service, remitente, date))
    
    # Escribe los gastos en la pestaña 'gastos'
    for email in emails:
        expensive_shop = email['expensive_shop']
        expensive_datetime_str = email['expensive_datetime_str']
        expensive_datetime = datetime.strptime(expensive_datetime_str, '%d/%m/%Y %H:%M')

        expensive_total = email['expensive_total']
        shop = shops_dict.get(expensive_shop, {'category' : 'otros', 'name' : expensive_shop})
        print(f"shop : {shop}")
        category = shop['category']
        shop_name = shop['name']
        if expensive_datetime and expensive_shop and expensive_total:
            write_expensive(sheet, shop_name, expensive_datetime.date(), expensive_datetime.time(), expensive_total, category)
            print(f"Gasto registrado: {expensive_datetime}, {expensive_shop}, {expensive_total}, {category}")

