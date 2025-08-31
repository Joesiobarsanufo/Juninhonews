import html
import logging
import os
import random
import time
import json
from datetime import datetime, timedelta

import ephem
import pandas as pd
import pytz
import requests
from bs4 import BeautifulSoup # lxml precisará estar instalado para 'xml' parser

# --- Configuração básica de logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s')

# --- Constantes Globais ---
NEWS_API_URL = "https://newsapi.org/v2/everything"
COINGECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price"
BIBLE_GATEWAY_VOTD_URL = "https://www.biblegateway.com/votd/get/?format=xml&version=ARC"
PENSADOR_URL = "https://www.pensador.com/frases_de_pensadores_famosos/"
BOATOS_ORG_FEED_URL = "https://www.boatos.org/feed"
EXCHANGE_RATE_API_BASE_URL = "https://v6.exchangerate-api.com/v6"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
FUSO_BRASIL = pytz.timezone('America/Sao_Paulo')
FILE_PATH_DATAS_COMEMORATIVAS = "datas comemorativas.xlsx"

# --- Carregar Segredos das Variáveis de Ambiente ---
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
EXCHANGE_RATE_API_KEY = os.getenv('EXCHANGE_RATE_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- Funções Utilitárias e de Busca ---

def safe_request_get(url, params=None, timeout=10, max_retries=2, delay_seconds=2):
    print(f"[DEBUG] Executando safe_request_get para a URL: {url}")
    headers = {'User-Agent': USER_AGENT}
    if not ("newsapi.org" in url and NEWS_API_KEY) and not ("api.coingecko.com" in url):
        headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        headers['Pragma'] = 'no-cache'
        headers['Expires'] = '0'
    for attempt in range(max_retries):
        try:
            time.sleep(random.uniform(0.5, 1.5))
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            print(f"[DEBUG] Sucesso na requisição para {url} (Status: {response.status_code})")
            return response
        except requests.exceptions.RequestException as req_err:
            logging.error(f"Erro na requisição para {url}: {req_err}")
            print(f"[DEBUG] FALHA na requisição para {url}. Erro: {req_err}")
        if attempt < max_retries - 1:
            logging.info(f"Tentando novamente {url} em {delay_seconds}s... (Tentativa {attempt + 1}/{max_retries})")
        else:
            logging.error(f"Máximo de tentativas ({max_retries}) atingido para {url}.")
    return None

def get_cepea_prices_scraping() -> dict | str:
    logging.info("Iniciando busca de preços de commodities via Web Scraping do CEPEA.")
    print("\n--- [DEBUG] INICIANDO FUNÇÃO get_cepea_prices_scraping ---")
    cepea_urls = {
        "Milho": "https://www.cepea.esalq.usp.br/br/indicador/milho.aspx",
        "Soja": "https://www.cepea.esalq.usp.br/br/indicador/soja.aspx",
        "Boi Gordo": "https://www.cepea.esalq.usp.br/br/indicador/boi-gordo.aspx"
    }
    commodity_prices = {}
    for commodity_name, url in cepea_urls.items():
        print(f"[DEBUG] Buscando commodity: {commodity_name}")
        response = safe_request_get(url)
        print(f"[DEBUG] Resultado da busca para {commodity_name}: {'Recebeu resposta' if response else 'NÃO recebeu resposta'}")
        if not response:
            commodity_prices[commodity_name] = {"valor": "Falha na conexão", "data": ""}
            continue
        try:
            soup = BeautifulSoup(response.content, "html.parser")
            valor_div = soup.find('div', class_='imagen_indicador_valor')
            data_div = soup.find('div', class_='imagen_indicador_data')
            if valor_div and data_div:
                valor = valor_div.text.strip()
                data_str = data_div.text.strip().split(',')[-1].strip()
                commodity_prices[commodity_name] = {"valor": f"R$ {valor}", "data": data_str}
                print(f"[DEBUG] Sucesso ao extrair dados para {commodity_name}")
            else:
                commodity_prices[commodity_name] = {"valor": "Não encontrado", "data": "N/A"}
                print(f"[DEBUG] FALHA ao extrair dados para {commodity_name}: divs não encontradas.")
        except Exception as e:
            logging.exception(f"Erro ao fazer scraping para {commodity_name}: {e}")
            commodity_prices[commodity_name] = {"valor": "Erro no processo", "data": ""}
    print("--- [DEBUG] FINALIZANDO FUNÇÃO get_cepea_prices_scraping ---\n")
    return commodity_prices

# ... (O restante das suas funções como get_saudacao, fase_da_lua, etc., permanecem iguais)
def get_saudacao() -> str:
    hora_atual = datetime.now(FUSO_BRASIL).hour
    if 5 <= hora_atual < 12: return "Bom dia!"
    elif 12 <= hora_atual < 18: return "Boa tarde!"
    else: return "Boa noite!"

def fase_da_lua(data_str_ephem_format: str) -> str:
    try:
        date_observer = ephem.Date(data_str_ephem_format)
        moon = ephem.Moon(date_observer)
        illumination = moon.phase
        prev_date = ephem.Date(date_observer - 1)
        moon_prev = ephem.Moon(prev_date)
        is_waxing = illumination > moon_prev.phase
        if abs(illumination - moon_prev.phase) < 0.5 :
            pnm = ephem.previous_new_moon(date_observer)
            pfm = ephem.previous_full_moon(date_observer)
            if date_observer == pnm or date_observer == ephem.next_new_moon(date_observer): illumination = 0
            if date_observer == pfm or date_observer == ephem.next_full_moon(date_observer): illumination = 50
            is_waxing = True if pnm > pfm and date_observer > pnm else (False if pfm > pnm and date_observer > pfm else is_waxing)

        if illumination < 3: return "Lua Nova 🌑"
        if illumination > 97: return "Lua Nova (final) 🌑"
        if illumination >= 48 and illumination <= 52: return "Lua Cheia 🌕"
        if illumination >= 23 and illumination <= 27:
            return "Quarto Crescente 🌓" if is_waxing else "Quarto Minguante 🌗"
        if is_waxing:
            if illumination < 23: return "Lua Crescente Côncava 🌒"
            if illumination < 48: return "Lua Crescente Gibosa 🌔"
        else:
            if illumination > 77: return "Lua Minguante Côncava 🌘"
            if illumination > 52: return "Lua Minguante Gibosa 🌖"
        logging.warning(f"Fase da lua (ilum: {illumination}%, crescendo: {is_waxing}) não encaixou, usando fallback.")
        return "Fase Crescente (aprox.) 🌔" if is_waxing else "Fase Minguante (aprox.) 🌖"
    except Exception as e:
        logging.exception(f"Erro ao calcular fase da lua para '{data_str_ephem_format}': {e}")
        return "Fase da lua
