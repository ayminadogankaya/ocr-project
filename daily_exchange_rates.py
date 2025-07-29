import requests
import pyodbc
import xml.etree.ElementTree as ET
from datetime import datetime

def fetch_specific_exchange_rates():
    # Belirtilen tarihe ait URL
    url = "https://www.tcmb.gov.tr/kurlar/202505/29052025.xml"
    response = requests.get(url)
    
    # Eğer hata olursa, raise edelim
    if response.status_code == 404:
        raise Exception(f"Veri çekilemedi: {response.status_code}")
    
    return response.content

def parse_and_insert_data(xml_data):
    tree = ET.ElementTree(ET.fromstring(xml_data))
    root = tree.getroot()

    server = 'DESKTOP-6OQRVBE\\SQLEXPRESS'  # Kendi server adınız
    database = 'OCRPROJECT'
    connection_string = f'DRIVER={{SQL Server}};SERVER={server};DATABASE={database};Trusted_Connection=yes;'
    
    conn = pyodbc.connect(connection_string)
    cursor = conn.cursor()

    # XML'den gerekli verileri alıyoruz
    for currency in root.findall('Currency'):
        code = currency.get('CurrencyCode')
        unit = currency.find('Unit').text
        name = currency.find('Isim').text
    
        forex_buying = currency.find('ForexBuying').text
        forex_selling = currency.find('ForexSelling').text
        banknote_buying = currency.find('BanknoteBuying').text
        banknote_selling = currency.find('BanknoteSelling').text
    
        # Eğer veri None değilse, virgülleri noktaya çevirip float'a çeviriyoruz
        forex_buying = float(forex_buying.replace(',', '.')) if forex_buying else None
        forex_selling = float(forex_selling.replace(',', '.')) if forex_selling else None
        banknote_buying = float(banknote_buying.replace(',', '.')) if banknote_buying else None
        banknote_selling = float(banknote_selling.replace(',', '.')) if banknote_selling else None
    
        insert_query = """
        INSERT INTO DovizKurlari (Date, CurrencyCode, Unit, Currency, ForexBuying, ForexSelling, BanknoteBuying, BanknoteSelling)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor.execute(insert_query, datetime.now().strftime('%Y-%m-%d'), code, unit, name, forex_buying, forex_selling, banknote_buying, banknote_selling)

    conn.commit()
    cursor.close()
    conn.close()

def main():
    try:
        print("Belirtilen tarihe ait veri çekiliyor...")
        xml_data = fetch_specific_exchange_rates()
        parse_and_insert_data(xml_data)
        print("Veriler başarıyla tabloya yazıldı.")
    except Exception as e:
        print(f"Hata: {e}")

# Programı çalıştır
main()