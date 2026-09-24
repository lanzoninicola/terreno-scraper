# Terreno Scraper — Pato Branco

Monitora 27 sites de imóveis + 3 anúncios individuais em busca de terrenos em
Pato Branco/PR, filtra por preço (R$ 150k–300k) e avisa por WhatsApp quando
sai um anúncio novo (ou quando um anúncio já visto muda de preço). Terrenos
com área ≥ 350 m² vêm marcados com ⭐ na mensagem.

## Como funciona
- `config.py` — lista de sites e critérios de filtro. Edite aqui pra
  adicionar/remover sites ou mudar faixa de preço/área.
- `scraper/base.py` — busca a página com Playwright (headless) e faz a
  extração genérica (preço "R$" + metragem "m²" perto de um link).
- `scraper/sites/` — um parser por "plataforma". A maioria usa o extrator
  genérico (`generic.py`); OLX tem um ajuste pra pegar o preço com desconto
  corretamente.
- `scraper/storage.py` — SQLite (`/data/listings.db`) guarda os anúncios já
  vistos, pra só notificar sobre o que é novo ou mudou de preço.
- `scraper/notifier.py` — dispara a mensagem via `POST
  https://www.amodomio.com.br/api/messages/text`.
- `main.py` — roda uma passada por todos os sites.
- `scheduler.py` — loop que chama `main.py` a cada `SCRAPE_INTERVAL_MINUTES`
  (padrão: 240 = 4h).

## Rodar local (teste)
```bash
pip install -r requirements.txt
playwright install --with-deps chromium

export AMODOMIO_API_KEY="sua-chave"
export TARGET_PHONE="5546999999999"   # seu número, com DDI+DDD
python main.py                         # roda uma vez
python scheduler.py                    # roda em loop
```

## Deploy no seu VPS (Dokploy)
1. Suba esta pasta pra um repositório git (ou direto via Dokploy "Deploy
   from folder").
2. No Dokploy, crie uma aplicação Docker Compose apontando pro
   `docker-compose.yml`.
3. Configure as variáveis de ambiente `AMODOMIO_API_KEY` e `TARGET_PHONE` no
   painel do Dokploy (não commitar no git).
4. Deploy. O container já sobe rodando o `scheduler.py` em loop.

O volume `terreno_data` garante que o histórico de anúncios (dedupe)
sobrevive a reinícios/redeploys do container.

## Sobre a cobertura de cada site (importante)
Testei de verdade a extração contra **OLX** e **ImovelWeb** — o padrão
"preço + metragem + link" bate certinho nesses dois. Para os outros ~25
sites (ZAP, Chaves na Mão, imobiliárias locais, plataforma imb.br, Trovit,
etc.), o projeto usa o mesmo extrator genérico como aposta razoável — a
maioria dos sites de imóveis brasileiros segue esse padrão visual — mas eu
não tenho como validar contra o HTML real de cada um dentro deste ambiente
(sem acesso de rede a esses domínios aqui).

**Recomendo, depois do primeiro deploy:**
1. Rodar `python main.py` uma vez e olhar o log — ele mostra quantos
   anúncios cada site retornou. Um site retornando 0 é sinal de que o
   extrator genérico não bateu com o layout dele.
2. Para os sites com 0 resultado, me manda o log (ou o HTML) que eu escrevo
   um parser dedicado em `scraper/sites/<nome>.py`, do mesmo jeito que fiz
   pro OLX.

Isso é normal em projetos de scraping multi-site — cada site troca de
layout com o tempo, então vale revisar de tempos em tempos.

## Anúncios individuais (não são busca)
`aliancapbimoveis`, o anúncio do Ciro Imóveis (Monte Belo) e o da Trento
(próx. PB Shopping) são páginas de UM anúncio específico, não uma lista.
Pra esses, o sistema não "descobre novidade" — ele avisa se o **preço
mudar** desde a última checagem (útil pra saber se abriu negociação).

## Ajustando os critérios
Em `config.py`:
```python
CRITERIA = {
    "price_min": 150_000,
    "price_max": 300_000,
    "area_priority_min": 350,
}
```
