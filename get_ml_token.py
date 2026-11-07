"""Rode UMA vez no seu PC:  python get_ml_token.py
Antes: crie um app grátis em https://developers.mercadolivre.com.br/devcenter
 - URI de redirect: https://www.google.com
 - Escopos: leitura (read) + offline_access
Vai gerar o PRIMEIRO refresh_token, que você coloca no Data Store do Make.
Depois disso o Make renova sozinho a cada execução."""
import urllib.parse
import requests

client_id = input("Client ID (App ID): ").strip()
client_secret = input("Client Secret: ").strip()
redirect = "https://www.google.com"
print("\nAbra este link, autorize e copie o valor de ?code=... da barra de endereço:\n")
print("https://auth.mercadolivre.com.br/authorization?" + urllib.parse.urlencode(
    {"response_type": "code", "client_id": client_id, "redirect_uri": redirect}))
code = input("\ncode: ").strip()
r = requests.post("https://api.mercadolibre.com/oauth/token", data={
    "grant_type": "authorization_code", "client_id": client_id, "client_secret": client_secret,
    "code": code, "redirect_uri": redirect}, headers={"accept": "application/json"})
print(r.status_code, r.json())
print("\nREFRESH TOKEN para o Make:", r.json().get("refresh_token"))
