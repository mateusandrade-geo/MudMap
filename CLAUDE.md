# Contexto do projeto (para o Claude Code)

**MudMap**: segmentação e classificação mineral a partir de **mapas EDS** (MEV-EDS, exportados do
AZtec) de rochas sedimentares (lamitos). A entrada é **um mapa por elemento químico** (Si, Al, Fe,
Mg, K, Ca, Na, Ti, S…), TIFF colorido de matiz fixo em que o brilho codifica a concentração, mais a
imagem de elétrons (BSE), todos alinhados pixel a pixel e com tamanho de pixel conhecido
(metadados do TIFF). Amostra real no repositório: **RJS0649RJ**, sítios 1.1 e 1.2.

## Princípio inegociável: classificação determinística

A atribuição de mineral a cada pixel/região sai de **código determinístico** (regras
estequiométricas sobre o vetor de frações de cátion, ou clustering), nunca de julgamento "no olho"
do modelo. O papel do agente é escrever, rodar e explicar o código, e resumir evidências (ex.:
"região X: Si dominante, cátions ≈ 0 → candidata a quartzo"). Isso mantém tudo reprodutível e
auditável.

## Fluxo de trabalho

O passo a passo com o usuário (reconhecer → segmentar um mineral por vez → revisar → calibrar →
relatório → trocar de sítio) está na skill **`.claude/skills/mudmap/SKILL.md`** — siga-a.

## Estrutura

```
app/mudmap_studio/        MudMap Studio (PyQt6): Inspetor, Edição, Segmentar, Relatório
  nucleo/                 lógica sem Qt; importa scripts/common.py e segmentar.py (mesma matemática)
  nucleo/exemplo.py       gerador do projeto de EXEMPLO sintético (mapas AZtec falsos + config)
  ui/                     interface
  recursos/               ícone e config do exemplo (vão dentro do .exe)
app/testes/               validar_nucleo.py, testar_interface.py, estresse_4096.py
app/build_exe.ps1         gera o .exe (PyInstaller, Windows)
scripts/                  pipeline por linha de comando (um script por etapa; ver SKILL.md)
config/classificacao.yaml regras dos minerais do sítio ATIVO (ordem = prioridade; id = posição)
estado/                   estado do sítio ativo: rotulos.npy (0 = livre, 1..N = mineral),
                          progresso.json, clusters.npy/.json, rotulos_prev.npy (backup de 1 passo)
sitios/<s>/               sítios arquivados (estado/, classificacao_<s>.yaml, info.json)
EDS/<amostra>/<sítio>/    mapas brutos do AZtec (<El> Wt% Map Data N.tif, Electron Image N.tif)
amostras/*.mudmap         pacotes prontos para abrir no app (um por sítio)
saida/                    tudo o que os scripts geram (fora do git)
exemplo/                  projeto sintético gerado por scripts/gerar_exemplo.py (fora do git)
```

## Como rodar

- Instalar: `pip install -r requirements.txt` (napari só em `requirements-napari.txt`).
- App: `python app/run_studio.py [arquivo.mudmap | --exemplo]` (precisa de tela).
- Scripts: na raiz do projeto, `python scripts/<script>.py` (caminhos relativos a config/, estado/).
- Sítios: `python scripts/ativar_sitio.py --listar` / `python scripts/ativar_sitio.py 1.1`.
- Exemplo sintético: `python scripts/gerar_exemplo.py` → `exemplo/` (rode os scripts de dentro dele).

## Testes (rode depois de mexer em app/ ou scripts/)

```bash
python app/testes/validar_nucleo.py [projeto]                 # núcleo do app × pipeline (asserts)
QT_QPA_PLATFORM=offscreen python app/testes/testar_interface.py [saida] [--raiz projeto]
python app/run_studio.py --autoteste amostras/RJS0649RJ_1.1.mudmap saida/auto.png .   # como o .exe é validado
```

`projeto` default = raiz do repositório (sítio ativo, dados reais); a CI roda também no exemplo
sintético (`python scripts/gerar_exemplo.py && (cd exemplo && python ../scripts/reconhecer.py)`).
Os testes não alteram config/estado do projeto (trabalham em cópias temporárias).

## Regras de mineral

Ficam em `config/classificacao.yaml`, como condições compostas (E lógico) sobre frações de cátion
normalizadas, ou modelos por região (`mapas_grupos`) + pós-filtro de `forma`. A ordem = prioridade
(primeiro que casa vence) e o id gravado em `rotulos.npy` = posição do mineral: não reordene nem
remova minerais de um projeto com rótulos. Discriminadores importam (p.ex. clorita × biotita pelo
Mg/Si e pelo K). Limiares devem ser calibrados a partir de grãos de referência
(`scripts/comparar.py --calibrar`), não chutados, e cada calibração fica registrada em comentário no
bloco do mineral (data, referência, métrica). Tamanhos em µm (`*_um`) viram px num único lugar
(`common.resolver_escala`).

## Convenções

- Coordenadas em convenção **(row, col)** = (y, x), como no napari e no scipy.
- "Presente" ≈ fração de cátion `> 0.08`; "ausente/traço" ≈ `< 0.03`; a faixa intermediária fica
  sem classe de propósito (pixels mistos de borda → revisar).
- Não incluir O nem C nas frações de cátion (O é discriminador fraco no EDS; C vem da resina epóxi).
- O app **reusa** as funções do pipeline (`app/mudmap_studio/nucleo/pipeline.py` importa
  `scripts/common.py` e `scripts/segmentar.py`): mudou a matemática num lugar, os dois mudam; o
  `validar_nucleo.py` confere que continuam idênticos.
- Todo script que grava `estado/rotulos.npy` salva antes `estado/rotulos_prev.npy` (1 nível de desfazer).
- Textos, comentários e mensagens em português.
