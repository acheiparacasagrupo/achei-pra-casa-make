"""Rode UMA vez no seu PC:  pip install google-auth-oauthlib  &&  python get_youtube_token.py
Antes: no Google Cloud Console crie um "ID do cliente OAuth" do tipo App para computador,
baixe o JSON como client_secret.json nesta pasta e ative a "YouTube Data API v3".
IMPORTANTE: na Tela de consentimento OAuth clique em "PUBLICAR APP" (status Em produção),
senão o refresh token expira em 7 dias."""
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json",
    scopes=["https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl"])
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nYT_CLIENT_ID     =", creds.client_id)
print("YT_CLIENT_SECRET =", creds.client_secret)
print("YT_REFRESH_TOKEN =", creds.refresh_token)
print("\nCole os 3 valores em GitHub > Settings > Secrets and variables > Actions.")
