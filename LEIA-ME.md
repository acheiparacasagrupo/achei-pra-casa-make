# Achei pra Casa — Shorts automáticos (100% grátis)

Make (agenda 3x/dia + renova token do ML)  →  GitHub Actions (busca produto, Gemini, vídeo real, narração, FFmpeg, YouTube)

## 1. GitHub (grátis)
1. Repositório **público** `achei-pra-casa-make` (público = minutos ilimitados no Actions) e suba todos estes arquivos.
2. Settings > Secrets and variables > Actions > **Secrets**:
   - `GEMINI_API_KEY` — https://aistudio.google.com/apikey
   - `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` — rode `get_youtube_token.py` no seu PC
   - `YT_COOKIES` (opcional) — cookies.txt do YouTube, se o yt-dlp for bloqueado no servidor
3. **Variables** (opcional): `PRIVACIDADE=private` nos primeiros testes; `SOMENTE_CREATIVE_COMMONS=false` libera qualquer vídeo (risco de direitos autorais).
4. Crie um token: github.com/settings/personal-access-tokens > Fine-grained > só este repo > Contents: Read and write.

## 2. Mercado Livre (grátis)
1. Crie um app em https://developers.mercadolivre.com.br/devcenter (redirect `https://www.google.com`).
2. Rode `get_ml_token.py` e pegue o primeiro `refresh_token`.
3. No Make > Data stores > token_mercadolivre > Add: key `ml`, refresh_token = o valor.

## 3. Make (já montado: "Achei pra Casa - Short automático")
- Módulo 2: troque `COLE_AQUI_CLIENT_ID_ML` e `COLE_AQUI_CLIENT_SECRET_ML`.
- Módulo 4: troque `SEU_USUARIO_GITHUB` na URL e `COLE_AQUI_TOKEN_GITHUB` no header.
- Run once → veja a aba Actions do GitHub rodar → ative o cenário.
Uso: ~4 operações por execução × 90/mês ≈ 360 de 1.000 grátis.

## Teste sem publicar
GitHub > Actions > "Novo Short" > Run workflow (dry_run = true) → baixe o vídeo em Artifacts.
