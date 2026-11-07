# Achei pra Casa — Shorts automáticos (100% grátis, sem API do ML e sem API do YouTube)

**GitHub Actions (3x por dia: 10:40, 16:10 e 20:20)**
1. Abre a página pública "Mais vendidos" do Mercado Livre (Cozinha, Organização, Limpeza, Banheiro, etc.)
2. Gemini escolhe o produto que resolve a dor mais forte e tem cara de viral
3. Pega o vídeo REAL do anúncio (clips do próprio Mercado Livre)
4. Gemini escreve título, descrição, tags e narração (dor → solução → CTA do grupo do WhatsApp)
5. Voz natural (edge-tts) + montagem 9:16 com FFmpeg (< 5 MB)
6. Publica o vídeo como Release e chama o webhook do Make

**Make (cenário "Achei pra Casa - Short automático")**
Webhook → baixa o vídeo → posta no YouTube (conta conectada no próprio Make)

## Secrets do GitHub
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey (grátis)
- `MAKE_WEBHOOK_URL` — URL do webhook do cenário no Make

## Variables opcionais
- `VOZ` (padrão pt-BR-AntonioNeural; opções pt-BR-FranciscaNeural, pt-BR-ThalitaNeural)
- `GRUPO_WHATSAPP` (padrão: link do grupo VIP)

## Teste
Actions > "Novo Short" > Run workflow (dry_run = true) → baixe o vídeo em Artifacts.
