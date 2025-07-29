import os
import re
from flask import Flask, request, render_template, redirect, url_for, flash, session, jsonify, make_response
import ocrmypdf
from pdf2image import convert_from_path
import cv2
import pytesseract
import numpy as np
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from PyPDF2 import PdfReader, PdfWriter
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict
import pyodbc
from functools import wraps
from decimal import Decimal
import datetime as dt
import subprocess
import schedule
import time
import threading
import json
from transformers import AutoTokenizer, AutoModelForTokenClassification
import torch
import pdfkit
from collections import defaultdict


try:
    import fitz  # PyMuPDF
except ImportError:
    print("PyMuPDF (fitz) modülü bulunamadı. Lütfen 'pip install pymupdf' komutunu kullanarak kurun.")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Flask Uygulaması ve Yapılandırma
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = 'kitoko_080621009'


# MSSQL Veritabanı bağlantısı
conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=DESKTOP-6OQRVBE\\SQLEXPRESS;'
    'DATABASE=OCRPROJECT;'
    'Trusted_Connection=yes;'
)

cursor = conn.cursor()

# Kullanıcı tablosunu oluşturma
cursor.execute('''
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Users' and xtype='U')
    CREATE TABLE Users (
        id INT PRIMARY KEY IDENTITY(1,1),
        username NVARCHAR(50) UNIQUE NOT NULL,
        password_hash NVARCHAR(200) NOT NULL
    )
''')
conn.commit()

# Azure Form Recognizer Bilgileri
FORM_RECOGNIZER_ENDPOINT =  "https://ocrprojeay.cognitiveservices.azure.com/"
FORM_RECOGNIZER_KEY = "37b67f02ea1840d58a63ab6765f9a1ce"

document_analysis_client = DocumentAnalysisClient(
    endpoint=FORM_RECOGNIZER_ENDPOINT,
    credential=AzureKeyCredential(FORM_RECOGNIZER_KEY)
)

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
path_wkhtmltopdf = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"  # kendi yolunu yaz
config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)


# Anahtar kelimeler
KEYWORDS = {
    "QTY": ["QTY", "Quantity", "Qty","QUANTITY", "Quantites", "QTY ORDERED", "qty ordered", "QUANTITY", "QUANTITES", "Qty ordered", 
            "Qty Ordered","ADET", "adet", "Adet", "Q.TY", "Miktar", "Q.ty", "Quantità"],

    "Product_Code": ["Product Code", "Article", "Article Type", "Ref. Code", "Item", "Item Code", "ITEM", "ITEM CODE", "KOD", "Product", "PRODUCT", "product"
                     "Part Number", "PART NUMBER", "PRODUCT CODE", "ARTICLE", "ARTICLE TYPE", "REF. CODE", "Part number", "part number", "TYPE", "Type", "prod. code", "prod.code"
                     "ITEM NO","KOD", "Material","Ürün Kodu", "STOK KOD/YAP.KOD", "Prj. Ref. / Label No ", "Prj.Ref./Label No ", "ITEM NR", "ÜRÜN KODU", "Code", "Articolo","ÜRÜN KODU" ],

    "Description": ["Description", "Product Description", "Catalog #", "DESCRIPTION", "PRODUCT DESCRIPTION","AÇIKLAMA", "açıklama", "Açıklama","FULL DESCRIPTION OF GOODS","PART", "Part", "part", 
                    "Product description", "Model #", "MALZEMENİN ADI", "Part Number/Desc", "Product Description", "PRODUCT No. (WATTAGE / VOLTAGE / COLOR)", "PRODUCT No.(WATTAGE/VOLTAGE/COLOR)",
                    "ÜRÜN DETAYLARI", "FULL DESCRIPTION OF GOODS", "description", "Descrizione", "ÜRÜN DETAYLARI"],

    "Unit_Price": ["Unit Price", "Price Per Unit", "Unit Cost", "Price per Unit", "price per unit", "UNIT COST", "Unit", "unit", "unit price", "NET BİRİM FİYAT"
                   "unit cost", "unit price", "UNIT PRICE", "UNIT Price", "price", "Price", "PRICE", "UNIT", "UNIT PRICE", "Net Value", "Prezzo" 
                   "NET VALUE", "net value", "Net Value", "BİRİM FİYAT", "Birim Fiyat", "birim fiyat", "NET PRICE", "net price", "Net Price", " BR.FİYAT", " BR. FİYAT", "NET BİRİM FİYAT"],

    "Extended_Amount": ["Extended Amount", "Amount", "Ext", "Total", "TOTAL AMOUNT", "TOTAL", "TOTAL PRICE", "EXTENDED AMOUNT", "Total Price", "TOTAL PRICE",
                        "AMOUNT", "EXT", "TOTAL Price", "EXT PRICE", "EXT Price", "ext price", "Ttotal", "total amount", "Total Amount", "TUTAR", "tutar","Importo" 
                        "Tutar", "Line Total", "NET PRICE", "Toplam", " TUTAR", "TOPLAM FİYAT", "TUTAR", "EXTENSION", "tot.price", ],

    "Grand_Total": ["Grand Total", "Total Amount", "total amount", "TOTAL AMOUNT", "Total", "TOTAL", "total grand total", "GRAND TOTAL", 
                    "Grand total", "Subtotal", "SUBTOTAL", "Sub-Total", "SUB-TOTAL", "sub-total", "Total Net", "total net", "TOTAL NET"],

    "Freight": ["Freight", "freight", "FREIGHT", "Shipping", "shipping", "SHIPPING", "Delivery", "DELIVERY", "delivery"],

    "Date": ["DATE", "Date", "Issue Date", "ISSUE DATE", "date", "issue date", "invoice date", "Invoice date", "Invoice Date", "INVOICE DATE", "QUATED", 
             "Quated", "quated", "Documant Date", "Documant date", "documant date", "DOCUMANT","Götzens"]
            
}

# daily_exchange_rates.py dosyasını çalıştıracak fonksiyon
def run_daily_exchange_rates():
    script_path = os.path.join(os.path.dirname(__file__), 'daily_exchange_rates.py')
    try:
        subprocess.run(['python', script_path], check=True)
        print("daily_exchange_rates.py başarıyla çalıştırıldı.")
    except subprocess.CalledProcessError as e:
        print(f"Hata: {e}")

def schedule_daily_task():
    schedule.every().day.at("16:00").do(run_daily_exchange_rates)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

def start_scheduler():
    scheduler_thread = threading.Thread(target=schedule_daily_task)
    scheduler_thread.daemon = True  
    scheduler_thread.start()


def format_date(date_string):
    
    date_patterns = [
        r"(\d{1,2})/(\d{1,2})/(\d{4})",    
        r"(\d{4})/(\d{1,2})/(\d{1,2})",    
        r"(\d{1,2})-(\d{1,2})-(\d{4})",    
        r"(\d{4})-(\d{1,2})-(\d{1,2})",    
        r"(\d{1,2})\.(\d{1,2})\.(\d{4})",  
    ]

    for pattern in date_patterns:
        match = re.search(pattern, date_string)
        if match:
            day, month, year = None, None, None

            
            if len(match.groups()) == 3:
                if int(match.group(1)) > 12:
                    day, month, year = match.group(1), match.group(2), match.group(3)
                else:
                    month, day, year = match.group(1), match.group(2), match.group(3)

           
            elif len(match.groups()) == 3:
                year, month, day = match.group(1), match.group(2), match.group(3)

            
            try:
                if day and month and year:
                    return f"{int(day):02}/{int(month):02}/{int(year)}"
            except ValueError:
                continue

    return None


def get_previous_business_day(extracted_date):
   
    date_obj = dt.datetime.strptime(extracted_date, "%Y-%m-%d").date()

    
    while True:
        
        date_obj -= dt.timedelta(days=1)
        
        while date_obj.weekday() >= 5:  
            date_obj -= dt.timedelta(days=1)

        
        sql_date = date_obj.strftime("%Y-%m-%d")
        query = f"SELECT COUNT(*) FROM DovizKurlari WHERE Date = '{sql_date}'"
        cursor.execute(query)
        count = cursor.fetchone()[0]

        if count > 0:
            break  

    return date_obj


def get_brands():
    query = "SELECT BrandName, BrandCode FROM Brands"
    cursor.execute(query)
    brands = cursor.fetchall()
    return brands

def get_exchange_rate_for_previous_business_day(extracted_date, currency_code):
    previous_business_day = get_previous_business_day(extracted_date)

    while True:
        sql_date = previous_business_day.strftime("%Y-%m-%d")
        query = f"SELECT BanknoteSelling, ForexSelling FROM DovizKurlari WHERE Date = '{sql_date}' AND CurrencyCode = '{currency_code}'"
        print(f"Executing SQL Query: {query}")
        cursor.execute(query)
        result = cursor.fetchone()

        if result:
            banknote_selling = result[0]
            forex_selling = result[1]

            if banknote_selling is not None:
                print(f"Using BanknoteSelling for {previous_business_day}: {banknote_selling}")
                return banknote_selling
            elif forex_selling is not None:
                print(f"BanknoteSelling is NULL, using ForexSelling instead for {previous_business_day}: {forex_selling}")
                return forex_selling
        
        
        previous_business_day -= dt.timedelta(days=1)
        while previous_business_day.weekday() >= 5:  
            previous_business_day -= dt.timedelta(days=1)
            
def process_pdf_date_and_get_currency(extracted_date, currency_code):
    exchange_rate_value = get_exchange_rate_for_previous_business_day(extracted_date, currency_code)

    if exchange_rate_value:
        print(f"Exchange rate for {currency_code} on previous business day: {exchange_rate_value}")
        return exchange_rate_value
    else:
        print(f"No exchange rate found for {currency_code} on previous business day.")
        return None


def handle_pdf_currency(sql_date, currency_code):
   
    exchange_rate_value = get_exchange_rate_for_previous_business_day(sql_date, currency_code)
    if exchange_rate_value:
        return exchange_rate_value
    else:
        print("Exchange rate not found.")
        return None


def convert_to_eur(total_sum, source_currency_rate, eur_tl_rate):
    """
    Herhangi bir para biriminden TL üzerinden EUR'ya dönüşüm yapar.

    Args:
    - total_sum: Kaynak para birimindeki toplam miktar.
    - source_currency_rate: Kaynak para biriminin TL karşılığı.
    - eur_tl_rate: EUR'nun TL karşılığı.

    Returns:
    - EUR karşılığı (Decimal türünde).
    """
    try:
        
        total_sum_decimal = Decimal(total_sum)
        source_currency_rate_decimal = Decimal(source_currency_rate)
        eur_tl_rate_decimal = Decimal(eur_tl_rate)

       
        if source_currency_rate_decimal > 0 and eur_tl_rate_decimal > 0:
            
            total_in_tl = total_sum_decimal * source_currency_rate_decimal
            
            total_in_eur = total_in_tl / eur_tl_rate_decimal
            
            
            print(f"[DEBUG] Total Sum (Source): {total_sum_decimal}")
            print(f"[DEBUG] Source-TL Rate: {source_currency_rate_decimal}")
            print(f"[DEBUG] EUR-TL Rate: {eur_tl_rate_decimal}")
            print(f"[DEBUG] Total in TL: {total_in_tl}")
            print(f"[DEBUG] Converted Total to EUR: {total_in_eur}")
            
            return total_in_eur
        else:
            print(f"Invalid exchange rates: Source Rate: {source_currency_rate_decimal}, EUR-TL Rate: {eur_tl_rate_decimal}")
            return None
    except Exception as e:
        print(f"Error during conversion: {e}")
        return None


def extract_date_with_layout_form_recognizer(pdf_path):
    with open(pdf_path, "rb") as f:
        poller = document_analysis_client.begin_analyze_document(
            model_id="prebuilt-layout", document=f)
    result = poller.result()

    date_data = None  

    for table in result.tables:
        for cell in table.cells:
            text = cell.content.strip()

            
            if any(keyword.lower() in text.lower() for keyword in KEYWORDS["Date"]):
                
                potential_date = format_date(text)
                if potential_date:
                    date_data = potential_date
                    break

                # Aynı sütunda, hemen altında tarih bilgisi varsa
                column_index = cell.column_index
                for below_cell in table.cells:
                    if below_cell.column_index == column_index and below_cell.row_index > cell.row_index:
                        potential_date = format_date(below_cell.content.strip())
                        if potential_date:
                            date_data = potential_date
                            break

    return date_data

# OCR fonksiyonu
def ocr_pdf(input_pdf, output_pdf, lang='eng'):
    try:
        ocrmypdf.ocr(input_pdf, output_pdf, force_ocr=True)
    except ocrmypdf.exceptions.PriorOcrFoundError:
        ocrmypdf.ocr(input_pdf, output_pdf, force_ocr=True)
    except ocrmypdf.exceptions.SubprocessOutputError as e:
        print(f"SubprocessOutputError: {e}")

# PDF dosyasını sayfalara ayıran fonksiyon
def split_pdf(input_pdf, output_folder):
    try:
        with open(input_pdf,"rb") as pdf_file:
            reader = PdfReader(pdf_file)
            page_files = []

            os.makedirs(output_folder, exist_ok=True)

            for i, page in enumerate(reader.pages):
                writer = PdfWriter()
                writer.add_page(page) 
                output_filename = os.path.join(output_folder, f"page_{i+1}.pdf")

                with open (output_filename, "wb") as (outputStream):
                    writer.write(outputStream)
                
                page_files.append(output_filename)
                print(f"Oluşturuldu: {output_filename}")

            return page_files
    except Exception as e:
        print(f"PDF'yi bölerken bir hata oluştu: {e}")
        return []

def extract_numeric_part(s):
    # Harfleri ve boşlukları kaldırarak yalnızca sayısal kısımları alır
    numeric_part = re.sub(r'[^\d,.-]', '', s)
    print(f"Original: {s}, Extracted Numeric Part: {numeric_part}")  # Hangi veriyi işlediğini görmek için
    return numeric_part if numeric_part else None

def extract_text_with_layout_form_recognizer(pdf_path):
    with open(pdf_path, "rb") as f:
        poller = document_analysis_client.begin_analyze_document(
            model_id="prebuilt-layout", document=f)
    result = poller.result()

    extracted_data = {
        "QTY": [],
        "Product_Code": [],
        "Description": [],
        "Unit_Price": [],
        "Extended_Amount": [],
        "Grand_Total": [],
        "Date": [],
        "Freight": []
    }

    freight_value = None  # Freight değeri için başlangıç değeri

    for table in result.tables:
        # Sütun indekslerini belirle
        qty_column_index = None
        product_code_column_index = None
        description_column_index = None
        unit_price_column_index = None
        extended_amount_column_index = None
        date_column_index = None

        for row in table.cells:
            # QTY sütunu indeksi
            if qty_column_index is None and any(keyword.lower() in row.content.lower() for keyword in KEYWORDS["QTY"]):
                qty_column_index = row.column_index
            # Product Code sütunu indeksi
            if product_code_column_index is None and any(keyword.lower() in row.content.lower() for keyword in KEYWORDS["Product_Code"]):
                product_code_column_index = row.column_index
            # Description sütunu indeksi
            if description_column_index is None and any(keyword.lower() in row.content.lower() for keyword in KEYWORDS["Description"]):
                description_column_index = row.column_index
            # Unit Price sütunu indeksi
            if unit_price_column_index is None and any(keyword.lower() in row.content.lower() for keyword in KEYWORDS["Unit_Price"]):
                unit_price_column_index = row.column_index
            # Extended Amount sütunu indeksi
            if extended_amount_column_index is None and any(keyword.lower() in row.content.lower() for keyword in KEYWORDS["Extended_Amount"]):
                extended_amount_column_index = row.column_index
            # Date sütunu indeksi
            if date_column_index is None and any(keyword.lower() in row.content.lower() for keyword in KEYWORDS["Date"]):
                date_column_index = row.column_index

            # Freight değerini arıyoruz
            if 'freight' in row.content.lower():
                
                cell_index = row.column_index
                for cell in table.cells:
                    if (cell.column_index == cell_index + 1 and cell.row_index == row.row_index + 1 ) and cell.row_index >= row.row_index:
                        freight_value = extract_numeric_part(cell.content)
                        if freight_value:
                            extracted_data["Freight"].append(freight_value)
                            break
                
                if freight_value:
                    break
    

        # Sütunlar belirlendikten sonra, satırları kontrol etmeye başlayın
        current_row_index = None
        for cell in table.cells:
            if current_row_index is None or cell.row_index != current_row_index:
                if current_row_index is not None:
                    
                    if (current_row_data["QTY"] or current_row_data["Unit_Price"] or current_row_data["Extended_Amount"]) and \
                        (current_row_data["Product_Code"] or current_row_data["Description"]):
                        
                        extracted_data["QTY"].append(current_row_data["QTY"] if current_row_data["QTY"] else "")
                        extracted_data["Product_Code"].append(current_row_data["Product_Code"] if current_row_data["Product_Code"] else "")
                        extracted_data["Description"].append(current_row_data["Description"] if current_row_data["Description"] else "")
                        extracted_data["Unit_Price"].append(current_row_data["Unit_Price"] if current_row_data["Unit_Price"] else "")
                        extracted_data["Extended_Amount"].append(current_row_data["Extended_Amount"] if current_row_data["Extended_Amount"] else "")
                        extracted_data["Date"].append(current_row_data["Date"] if current_row_data["Date"] else "")

                
                current_row_index = cell.row_index
                current_row_data = {
                    "QTY": None,
                    "Product_Code": None,
                    "Description": None,
                    "Unit_Price": None,
                    "Extended_Amount": None,
                    "Date": None
                }

            # QTY kontrolü
            if cell.column_index == qty_column_index:
                current_row_data["QTY"] = extract_numeric_part(cell.content)
            # Product Code kontrolü
            if cell.column_index == product_code_column_index:
                current_row_data["Product_Code"] = cell.content.strip()
            # Description kontrolü
            if cell.column_index == description_column_index:
                current_row_data["Description"] = cell.content.strip()
            # Unit Price kontrolü
            if cell.column_index == unit_price_column_index:
                current_row_data["Unit_Price"] = extract_numeric_part(cell.content)
            # Extended Amount kontrolü
            if cell.column_index == extended_amount_column_index:
                current_row_data["Extended_Amount"] = extract_numeric_part(cell.content)
            # Date kontrolü
            if cell.column_index == date_column_index or any(keyword.lower() in cell.content.lower() for keyword in KEYWORDS["Date"]):
                current_row_data["Date"] = format_date(cell.content.strip())

        # Son satır
        if (current_row_data["QTY"] or current_row_data["Unit_Price"] or current_row_data["Extended_Amount"]) and \
            (current_row_data["Product_Code"] or current_row_data["Description"]):
            extracted_data["QTY"].append(current_row_data["QTY"] if current_row_data["QTY"] else "")
            extracted_data["Product_Code"].append(current_row_data["Product_Code"] if current_row_data["Product_Code"] else "")
            extracted_data["Description"].append(current_row_data["Description"] if current_row_data["Description"] else "")
            extracted_data["Unit_Price"].append(current_row_data["Unit_Price"] if current_row_data["Unit_Price"] else "")
            extracted_data["Extended_Amount"].append(current_row_data["Extended_Amount"] if current_row_data["Extended_Amount"] else "")
            extracted_data["Date"].append(current_row_data["Date"] if current_row_data["Date"] else "")

    print(f"Extracted Data: {extracted_data}")  
    return extracted_data
    
def perform_ocr(segmented_characters):
    recognized_text = []
    for character in segmented_characters:
        text = pytesseract.image_to_string(character, config='--psm 10 --oem 3')
        recognized_text.append(text.strip())
    return recognized_text

def convert_to_number(amount):
    if amount is None:
        return None 
    try:
        if ',' in amount and '.' in amount:
            if amount.rfind(',') > amount.rfind('.'):
                amount = amount.replace('.', '').replace(',','.')
            else:
                amount = amount.replace(',', '')
        elif ',' in amount:
            amount = amount.replace(',', '.')
        return float(amount)
    except ValueError:
        return None

def process_pages(page_files):
    aggregated_data = {
        "QTY": [],
        "Product_Code": [],
        "Description": [],
        "Unit_Price": [],
        "Extended_Amount": [],
        "Grand_Total": [],
        "Freight": [], 
        "Date": []
    }

    for page_file in page_files:
        print(f"Processing page: {page_file}")

        page_data = extract_text_with_layout_form_recognizer(page_file)

        print(f"Extracted Data for {page_file}: {page_data}")

        
        date_data = extract_date_with_layout_form_recognizer(page_file)
        if date_data:
            aggregated_data["Date"].append(date_data)

        max_len = max(len(page_data["QTY"]), len(page_data["Product_Code"]), len(page_data["Description"]), len(page_data["Unit_Price"]), len(page_data["Extended_Amount"]), len(page_data["Freight"]))

        for i in range(max_len):
            qty = page_data["QTY"][i].strip() if i < len(page_data["QTY"]) and page_data["QTY"][i] else ""
            product_code = page_data["Product_Code"][i].strip() if i < len(page_data["Product_Code"]) and page_data["Product_Code"][i] else ""
            description = page_data["Description"][i].strip() if i < len(page_data["Description"]) and page_data["Description"][i] else ""
            unit_price = page_data["Unit_Price"][i].strip() if i < len(page_data["Unit_Price"]) and page_data["Unit_Price"][i] else ""
            extended_amount = page_data["Extended_Amount"][i].strip() if i < len(page_data["Extended_Amount"]) and page_data["Extended_Amount"][i] else ""
            freight = page_data["Freight"][i].strip() if i < len(page_data["Freight"]) and page_data["Freight"][i] else ""

            
            if not qty and not unit_price and not extended_amount and (description or product_code):
                print(f"Skipping row: Description={description}, Product_Code={product_code}")
                continue

            
            if qty or extended_amount:
                aggregated_data["QTY"].append(qty)
                aggregated_data["Product_Code"].append(product_code)
                aggregated_data["Description"].append(description)
                aggregated_data["Unit_Price"].append(unit_price)
                aggregated_data["Extended_Amount"].append(extended_amount)
                if freight:
                    aggregated_data["Freight"].append(freight)

        
        aggregated_data["Grand_Total"].extend(page_data["Grand_Total"])

    return aggregated_data

def validate_password(password):
    if len(password) < 8:
        return "Şifre en az 8 karakter uzunluğunda olmalıdır."
    if not re.search(r"[A-Z]", password):
        return "Şifre en az bir büyük harf içermelidir."
    if not re.search(r"[a-z]", password):
        return "Şifre en az bir küçük harf içermelidir."
    if not re.search(r"[0-9]", password):
        return "Şifre en az bir sayısal karakter içermelidir."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return "Şifre en az bir özel karakter içermelidir."
    return None  


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Giriş sayfası
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        print(f"Submitted Username: {username}, Password: {password}")  

        
        cursor.execute("SELECT * FROM Users WHERE username=?", (username,))
        user = cursor.fetchone()

        if user:
            print(f"User Found: {user}")  

            
            if check_password_hash(user[2], password):
                session['user_id'] = user[0]
                session['username'] = user[1]  
                session['email'] = user[3]    
                flash('Giriş başarılı!', 'success')
                return redirect(url_for('index'))  
            else:
                flash('Hatalı şifre!', 'danger')
                print("Password incorrect")  
        else:
            flash('Kullanıcı bulunamadı!', 'danger')
            print("User not found") 

    return render_template('login.html')
    


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Geçersiz e-posta formatı', 'danger')
            return redirect(url_for('register'))

      
        password_hash = generate_password_hash(password)

        password_error = validate_password(password)
        if password_error:
            flash(password_error, 'danger')
            return render_template('register.html')

        
        try:
            
            cursor.execute("INSERT INTO Users (username, email, password_hash) VALUES (?, ?, ?)", (username, email, password_hash))
            conn.commit()
            flash('Kayıt başarılı! Giriş yapabilirsiniz.', 'success')
            return redirect(url_for('login'))
        except pyodbc.IntegrityError:
            flash('Kullanıcı adı veya e-posta zaten mevcut!', 'danger')

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Oturum kapatıldı.', 'info')
    return redirect(url_for('login'))


@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        if 'pdf_file' not in request.files:
            return 'No file part'
        file = request.files['pdf_file']
        if file.filename == '':
            return 'No selected file'
        if file:
            currency_code = request.form['currency']
            selected_brand = request.form['brand']  
            freight_value = request.form.get('freight', '')  
            invoice_number = request.form.get('invoice_number', '')  
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(file_path)

           
            split_pdf_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'split_pages')
            os.makedirs(split_pdf_folder, exist_ok=True)
            page_files = split_pdf(file_path, split_pdf_folder)

           
            aggregated_data = process_pages(page_files)

            
            total_sum = 0.0
            error_list = []
            for i in range(len(aggregated_data["Extended_Amount"])):
                qty = aggregated_data["QTY"][i].strip() if i < len(aggregated_data["QTY"]) else None
                amount = aggregated_data["Extended_Amount"][i]
                unit_price = aggregated_data["Unit_Price"][i].strip() if i < len(aggregated_data["Unit_Price"]) else None

                if amount and unit_price:  
                    print(f"Orijinal Extended Amount: '{amount}', Unit Price: '{unit_price}'")  

                    number = convert_to_number(amount)
                    if number is not None:
                        total_sum += number
                        print(f"Eklenmiş Extended Amount: {number}, Yeni Toplam: {total_sum}")  
                    else:
                        error_list.append(amount)
                        print(f"Extended Amount değeri '{amount}' sayıya dönüştürülemedi.")

            
            if freight_value:
                try:
                    freight_number = convert_to_number(freight_value)
                    if freight_number is not None:
                        total_sum += freight_number  
                        freight_formatted = f"{freight_number:,.2f} {currency_code}"
                    else:
                        freight_formatted = "Invalid Freight"  
                except Exception as e:
                    print(f"Freight değeri işlenirken hata: {e}")
                    freight_formatted = "Invalid Freight"
            else:
                freight_formatted = "N/A"  

            
            grand_total_formatted = f"{total_sum:,.2f} {currency_code}"  
            
            grand_total_in_eur = None

            extracted_date = aggregated_data["Date"][0] if aggregated_data["Date"] else "N/A"
            
            date_missing = extracted_date == "N/A"

            
            exchange_rate_value = None
            eur_rate = None

            if not date_missing:  
                date_obj = datetime.strptime(extracted_date, "%d/%m/%Y")
                sql_date = date_obj.strftime("%Y-%m-%d")
                exchange_rate_value = get_exchange_rate_for_previous_business_day(sql_date, currency_code)

                if exchange_rate_value:
                    print(f"Exchange Rate for {currency_code} on {sql_date}: {exchange_rate_value}")
                
                
                if currency_code != "EUR":
                    eur_rate = get_exchange_rate_for_previous_business_day(sql_date, "EUR")
                    if eur_rate:
                        print(f"EUR Exchange Rate on {sql_date}: {eur_rate}")  
                        grand_total_in_eur = convert_to_eur(total_sum, exchange_rate_value, eur_rate)
                        if grand_total_in_eur:
                            print(f"Converted Grand Total to EUR: {grand_total_in_eur}")
                        else:
                            print("Conversion to EUR failed!")  
                    else:
                        print("EUR rate not found in database!")  

            return render_template('verify.html',
                                   extracted_data=aggregated_data,
                                   filename=file.filename,
                                   parsed_data=aggregated_data,
                                   grand_total=f"{total_sum:,.2f} {currency_code}",
                                   grand_total_in_eur=f"{grand_total_in_eur:,.2f} EUR" if grand_total_in_eur else "N/A",  
                                   freight=freight_formatted,
                                   upload_date=extracted_date,
                                   currency=currency_code,
                                   exchange_rate=f"{exchange_rate_value:,.4f}" if exchange_rate_value else "N/A",
                                   date_missing=date_missing,
                                   selected_brand=selected_brand,
                                   invoice_number=invoice_number)  

    
    brands = get_brands()

    return render_template('index.html', brands=brands)

def log_feedback(username, document_id, field_name, predicted, corrected):
    if predicted != corrected:
        cursor.execute("""
            INSERT INTO FeedbackLogs (Username, DocumentID, FieldName, PredictedValue, CorrectedValue)
            VALUES (?, ?, ?, ?, ?)
        """, (username, document_id, field_name, predicted, corrected))
        conn.commit()

def convert_to_number(val):
    try:
        val = str(val).strip().replace(" ", "")
        
        if "," in val and "." in val:
            val = val.replace(".", "").replace(",", ".")
        
        elif "," in val:
            val = val.replace(",", ".")
        
        return float(val)
    except:
        return 0.0


@app.route('/verify', methods=['POST'])
@login_required
def verify():
    filename = request.form['filename']
    currency = request.form['currency']
    selected_brand = request.form.get('brand', '').strip()
        


    if not selected_brand:
        selected_brand = request.form.get('selected_brand', '').strip()  
        print("Seçilen marka (BrandName):", selected_brand)
    invoice_number = request.form.get('invoice_number', '')
    
    grand_total_value_float = 0.0
    i = 0
    while f"Extended_Amount_{i}" in request.form:
        extended_str = request.form.get(f"Extended_Amount_{i}", "").strip()
        amount = convert_to_number(extended_str)
        if amount is not None:
            grand_total_value_float += amount
        i += 1


    freight_value = request.form.get('freight_value', None)
    if freight_value:
        try:
            freight_value_float = float(freight_value.replace(",", ""))
            grand_total_value_float += freight_value_float
        except ValueError:
            freight_value_float = None
    else:
        freight_value_float = "N/A"

    parsed_data = {
        "QTY": [],
        "Product_Code": [],
        "Description": [],
        "Unit_Price": [],
        "Extended_Amount": [],
        "Date": []
    }

    i = 0
    while f"QTY_{i}" in request.form:
        parsed_data["QTY"].append(request.form[f"QTY_{i}"])
        parsed_data["Product_Code"].append(request.form[f"Product_Code_{i}"])
        parsed_data["Description"].append(request.form[f"Description_{i}"])
        parsed_data["Unit_Price"].append(request.form[f"Unit_Price_{i}"])
        parsed_data["Extended_Amount"].append(request.form[f"Extended_Amount_{i}"])
        parsed_data["Date"].append(request.form.get(f"Date_{i}", "N/A"))
        i += 1

    manual_date = request.form.get('manual_date')
    sql_date = None

    if manual_date:
        try:
            sql_date = datetime.strptime(manual_date, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            flash("Geçersiz tarih formatı (manual). Lütfen yyyy-mm-dd biçiminde girin.", "danger")
            return redirect(url_for('index'))
    elif parsed_data["Date"] and parsed_data["Date"][0] != "N/A":
        try:
            sql_date = datetime.strptime(parsed_data["Date"][0], "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            flash("PDF'ten çıkarılan tarih biçimi tanınamadı. Lütfen manuel olarak tarih girin.", "danger")
            return redirect(url_for('index'))

    exchange_rate_value = get_exchange_rate_for_previous_business_day(sql_date, currency) if sql_date else None

    grand_total_in_eur = None
    if sql_date and currency != "EUR" and exchange_rate_value:
        eur_rate = get_exchange_rate_for_previous_business_day(sql_date, "EUR")
        if eur_rate:
            grand_total_in_eur = convert_to_eur(grand_total_value_float, exchange_rate_value, eur_rate)

    grand_total = f"{grand_total_value_float:,.2f} {currency}"

    if sql_date:
        print(" İşlenecek tarih:", sql_date)
        conn.autocommit = True

        try:
            cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'Data'")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    CREATE TABLE Data (
                        id INT PRIMARY KEY IDENTITY(1,1),
                        BrandName NVARCHAR(100),
                        InvoiceNumber NVARCHAR(50),
                        Date DATE,
                        QTY NVARCHAR(50),
                        Product_Code NVARCHAR(100),
                        Description NVARCHAR(255),
                        Unit_Price NVARCHAR(50),
                        Extended_Amount NVARCHAR(50),
                        Currency NVARCHAR(10),
                        Grand_Total NVARCHAR(50),
                        Freight NVARCHAR(50),
                        Exchange_Rate NVARCHAR(50),
                        Created_At DATETIME DEFAULT GETDATE()
                    )
                """)
                conn.commit()

            row_count = len(next(iter(parsed_data.values()), []))
            print(" Kaydedilecek satır sayısı:", row_count)

            document_id = hash(filename)
            username = session.get('username', 'Unknown')

            for i in range(row_count):

                    
                predicted_qty = parsed_data['QTY'][i]
                predicted_price = parsed_data['Unit_Price'][i]
                predicted_desc = parsed_data['Description'][i]

                
                corrected_qty = request.form.get(f"QTY_{i}", "")
                corrected_price = request.form.get(f"Unit_Price_{i}", "")
                corrected_desc = request.form.get(f"Description_{i}", "")

                
                log_feedback(username, document_id, 'QTY', predicted_qty, corrected_qty)
                log_feedback(username, document_id, 'Unit_Price', predicted_price, corrected_price)
                log_feedback(username, document_id, 'Description', predicted_desc, corrected_desc)


                insert_query = """
                    INSERT INTO Data 
                    (BrandName, InvoiceNumber, Date, QTY, Product_Code, Description, Unit_Price, 
                     Extended_Amount, Currency, Grand_Total, Freight, Exchange_Rate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                cursor.execute(insert_query, (
                    selected_brand,
                    invoice_number,
                    sql_date,
                    parsed_data['QTY'][i],
                    parsed_data['Product_Code'][i],
                    parsed_data['Description'][i],
                    parsed_data['Unit_Price'][i],
                    parsed_data['Extended_Amount'][i],
                    currency,
                    grand_total,
                    freight_value_float,
                    f"{exchange_rate_value:,.4f}" if exchange_rate_value else "N/A"
                ))

            conn.commit()
            print(" Tüm veriler başarıyla kaydedildi.")
            flash(f'Veriler başarıyla "{selected_brand}" için dbo.Data tablosuna kaydedildi!', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            print("Kayıt sırasında hata oluştu:", e)
            flash("Veri kaydedilirken bir hata oluştu.", "danger")
            return redirect(url_for('index'))

    else:
        flash('Lütfen geçerli bir tarih girin.', 'danger')
        return redirect(url_for('index'))

    user = session.get('user', {})
    return render_template('verify.html',
                           filename=filename,
                           parsed_data=parsed_data,
                           currency=currency,
                           grand_total=f"{grand_total_value_float:,.2f} {currency}",
                           freight=freight_value_float,
                           exchange_rate=f"{exchange_rate_value:,.4f}" if exchange_rate_value else "N/A",
                           image_filenames=request.form.getlist('image_filenames'),
                           selected_brand=selected_brand,
                           extracted_data={"Date": [manual_date] if manual_date else parsed_data["Date"]},
                           invoice_number=invoice_number,
                           username=user.get('username', 'Unknown'),
                           user_email=user.get('email', 'Unknown'),
                           user_role=user.get('role', 'Unknown'))

@app.route('/add_new_record', methods=['POST'])
def add_new_record():
    try:
        
        data = request.get_json()
        if not data:
            return "Veri alınamadı", 400

        
        product_code = data.get('Product_Code')
        description = data.get('Description')
        quantity = data.get('Quantity')
        unit_price = data.get('Unit_Price')
        extended_amount = data.get('Extended_Amount')

        
        cursor.execute("""
            INSERT INTO Deletedrows (Product_Code, Description, Quantity, Unit_Price, Extended_Amount) 
            VALUES (?, ?, ?, ?, ?)
        """, (product_code, description, quantity, unit_price, extended_amount))

        conn.commit()  

        return '', 200  

    except Exception as e:
        print(f"Veritabanı hatası: {e}")  
        return "Sunucu hatası", 500


@app.route('/restore_row/<int:row_id>', methods=['POST'])
@login_required
def restore_row(row_id):
    
    cursor.execute("DELETE FROM Deletedrows WHERE id = ?", (row_id,))
    conn.commit()

    return '', 200

@app.route('/records')
@login_required
def records():
    return render_template('records.html')


def get_brands():
    cursor.execute("SELECT BrandName FROM Brands")
    return [row[0] for row in cursor.fetchall()]

@app.route('/get_brands')
def get_brands_api():
    brands = get_brands()  
    return jsonify(brands)


@app.route('/get_data')
def get_data():
    brand = request.args.get('brand')
    date = request.args.get('date')

    query = "SELECT * FROM Data WHERE BrandName = ?"
    params = [brand]

    if date:
        query += " AND Date = ?"
        params.append(date)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    
 
    columns = [column[0] for column in cursor.description]
    result = [dict(zip(columns, row)) for row in rows]

    return jsonify({'data': result})

def parse_float(val):
    try:
        val = str(val).strip()
            
        if ',' in val and '.' in val:
            val = val.replace('.', '').replace(',', '.')
            
        elif ',' in val:
            val = val.replace(',', '.')
            
        return float(val)
    except:
        return 0.0



@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    summary = None
    chart_data = None



    def parse_int(val):
        try:
            return int(str(val).replace(',', '').replace('.', ''))
        except:
            return 0

   
    cursor.execute("SELECT DISTINCT BrandName FROM dbo.Brands")
    brand_rows = cursor.fetchall()
    brands = [row[0] for row in brand_rows]

    if request.method == 'POST':
        brand = request.form.get('brand')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')

        query = """
            SELECT Date, InvoiceNumber, Product_Code, QTY, Extended_Amount
            FROM dbo.Data
            WHERE BrandName = ?
            AND Date BETWEEN ? AND ?
        """
        cursor.execute(query, (brand, start_date, end_date))
        rows = cursor.fetchall()

        if not rows:
            return render_template('dashboard.html', summary=None, chart_data=None, brands=brands)

        # Summary
        total_invoices = len(set(row.InvoiceNumber for row in rows))
        total_amount = sum(parse_float(row.Extended_Amount) for row in rows)

        product_count = defaultdict(int)
        for row in rows:
            product_count[row.Product_Code] += parse_int(row.QTY)
        top_product = max(product_count.items(), key=lambda x: x[1])[0]

        summary = {
            'total_invoices': total_invoices,
            'total_amount': f"{total_amount:.2f}",
            'top_product': top_product
        }

        
        sales_by_date = defaultdict(float)
        for row in rows:
            date_str = row.Date.strftime('%Y-%m-%d') if isinstance(row.Date, datetime) else str(row.Date)
            sales_by_date[date_str] += parse_float(row.Extended_Amount)

        chart_sales_by_date = {
            'labels': list(sales_by_date.keys()),
            'datasets': [{
                'label': 'Daily Sales',
                'data': list(sales_by_date.values()),
                'fill': False,
                'borderColor': '#c62828', 
                'backgroundColor': 'rgba(198, 40, 40, 0.15)',  
                'tension': 0.3  
            }]
        }

    
        chart_sales_by_product = {
            'labels': list(product_count.keys()),
            'datasets': [{
                'label': 'Quantity',
                'data': list(product_count.values()),
                'backgroundColor': 'rgba(198, 40, 40, 0.6)'
            }]
        }

        monthly_query = """
            SELECT 
                FORMAT(Date, 'yyyy-MM') AS Month,
                Extended_Amount,
                Currency,
                Exchange_Rate
            FROM dbo.Data
            WHERE BrandName = ?
            AND Date BETWEEN ? AND ?
        """
        cursor.execute(monthly_query, (brand, start_date, end_date))
        rows = cursor.fetchall()

        monthly_totals = defaultdict(float)

        for row in rows:
            month = row[0]
            amount = parse_float(row[1])
            currency = row[2]
            rate_from = parse_float(row[3])

            full_date = month + "-01"  

           
            if currency == "EUR":
                monthly_totals[month] += amount
            elif rate_from > 0:
                eur_rate = get_exchange_rate_for_previous_business_day(full_date, "EUR")
                if eur_rate:
                    converted_amount = convert_to_eur(amount, rate_from, eur_rate)
                    monthly_totals[month] += float(converted_amount)

        chart_sales_by_month = {
            'labels': list(monthly_totals.keys()),
            'datasets': [{
                'label': 'Monthly Total Sales (EUR)',
                'data': list(monthly_totals.values()),
                'fill': False,
                'borderColor': '#c62828',
                'backgroundColor': 'rgba(198, 40, 40, 0.15)',
                'tension': 0.3
            }]
        }

        currency_query = """
            SELECT Currency,
                SUM(CAST(REPLACE(REPLACE(Extended_Amount, '.', ''), ',', '.') AS FLOAT)) AS TotalAmount
            FROM dbo.Data
            WHERE BrandName = ?
            AND Date BETWEEN ? AND ?
            GROUP BY Currency
        """
        cursor.execute(currency_query, (brand, start_date, end_date))
        currency_data = cursor.fetchall()

        chart_currency_distribution = {
            'labels': [row[0] if row[0] else 'Unknown' for row in currency_data],
            'datasets': [{
                'label': 'Total Amount by Currency',
                'data': [row[1] for row in currency_data],
                'backgroundColor': [
                    'rgba(255, 99, 132, 0.6)',
                    'rgba(54, 162, 235, 0.6)',
                    'rgba(255, 206, 86, 0.6)',
                    'rgba(75, 192, 192, 0.6)',
                    'rgba(153, 102, 255, 0.6)'
                ],
                'borderColor': 'rgba(255,255,255,0.8)',
                'borderWidth': 1
            }]
        }
     
        chart_data = {
            'sales_by_date': json.dumps(chart_sales_by_date),
            'sales_by_product': json.dumps(chart_sales_by_product),
            'sales_by_month': json.dumps(chart_sales_by_month),
            'currency_distribution': json.dumps(chart_currency_distribution)
        }

        return render_template('dashboard.html', summary=summary, chart_data=chart_data, brands=brands)


    return render_template('dashboard.html', summary=None, chart_data=None, brands=brands)



if __name__ == "__main__":
    app.run(debug=True)